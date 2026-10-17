"""三个独立实验：沙箱调用工具、脚本编排子 Agent、后台工具并发.

运行：python harness_example/advanced.py --lesson code-mode [--offline]
其余 lesson：workflow、background。默认连接本地 Ollama；offline 只替换模型决策。
源码断点都在 src/pydantic_ai_harness/pydantic_ai_harness/ 下面对应的能力目录。
"""

import argparse
import asyncio
from os import getenv
from typing import Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.run import AgentRunResult
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import BackgroundTools

Lesson = Literal['code-mode', 'workflow', 'background']

# 让本地小模型直接使用已给出的脚本，读者可先理解执行机制，再修改编排逻辑。
CODE = """import asyncio
quantities = await asyncio.gather(stock(product='book'), stock(product='pen'))
{'quantities': quantities, 'total': sum(quantities)}"""
# 单行脚本避免本地模型把代码换行重复转义为字面量反斜杠 n。
WORKFLOW = (
    "draft = await explainer(task='Explain the Agent loop in one sentence.'); "
    "await reviewer(task='Check this explanation and add where tools run: ' + draft)"
)


def scripted_model(calls: list[ToolCallPart]) -> FunctionModel:
    """离线模型发出固定工具请求；真实能力负责校验、执行和将结果写回消息."""
    step = 0

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal step
        if isinstance(messages[-1], ModelRequest):
            for part in messages[-1].parts:
                if isinstance(part, RetryPromptPart):
                    raise RuntimeError(f'离线实验工具调用失败：{part.content}')
        if step < len(calls):
            call = calls[step]
            if call.tool_name not in {tool.name for tool in info.function_tools}:
                raise RuntimeError(f'工具未注册：{call.tool_name}')
            step += 1
            return ModelResponse(parts=[call])
        # 后台完成消息由 ctx.enqueue 注入为 UserPromptPart，不是第二个 ToolReturnPart。
        observed: list[str] = []
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, ToolReturnPart):
                        observed.append(part.model_response_str())
                    elif isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        if part.content.startswith('Background tool '):
                            observed.append(part.content)
        return ModelResponse(parts=[TextPart('\n'.join(observed))])

    return FunctionModel(respond)


def worker_model(role: str) -> FunctionModel:
    """离线子 Agent 仍有独立的 Agent.run 和消息历史，只将推理替换为可观察的回显."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for message in reversed(messages):
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        return ModelResponse(parts=[TextPart(f'{role}: {part.content}')])
        raise RuntimeError('子 Agent 缺少任务消息')

    return FunctionModel(respond)


async def code_mode(model: Model) -> AgentRunResult[str]:
    """在 Monty 中执行 Python；嵌套 stock 调用仍经过核心工具管理器."""
    # 可选依赖延迟导入，让 background 实验不要求安装 Monty。
    from pydantic_ai_harness import CodeMode

    executed: list[str] = []
    agent = Agent(
        model, capabilities=[CodeMode(max_tool_calls=4)], model_settings={'temperature': 0, 'max_tokens': 512}
    )

    async def stock(product: str) -> int:
        """Return the quantity for book or pen in this fixed learning inventory."""
        # VS Code 在这里下断点，可以从真实宿主工具回看沙箱调用栈。
        quantity = {'book': 7, 'pen': 11}[product]
        executed.append(product)
        return quantity

    agent.tool_plain(stock)
    # 断点：code_mode/_toolset.py 的 call_tool；_monty_exec.py 的 MontyExecutor。
    # Python 调试器可进入宿主调度和 stock；Monty 的 Rust 沙箱内部需要原生调试器。
    async with agent:
        result = await agent.run(
            f'Call run_code exactly once with this code, then report the returned total:\n{CODE}',
            usage_limits=UsageLimits(request_limit=8, tool_calls_limit=8),
        )
    if sorted(executed) != ['book', 'pen']:
        raise RuntimeError(f'实验未完成：实际 stock 调用为 {executed!r}')
    return result


async def workflow(model: Model, *, offline: bool) -> AgentRunResult[str]:
    """一个沙箱脚本依次调用两个普通 Agent；后一个只收到脚本显式传入的任务."""
    from pydantic_ai_harness import DynamicWorkflow

    completed_agents: set[str | None] = set()

    async def child_completed(ctx: RunContext[None], *, result: AgentRunResult[str]) -> AgentRunResult[str]:
        if ctx.agent is not None:
            completed_agents.add(ctx.agent.name)
        return result

    explainer = Agent(
        worker_model('explainer') if offline else model,
        name='explainer',
        capabilities=[Hooks(after_run=child_completed)],
        model_settings={'temperature': 0, 'max_tokens': 256},
        description='Explain the Pydantic AI Agent loop.',
        instructions='Explain briefly: the model requests tools, the host executes them, then the model continues.',
    )
    reviewer = Agent(
        worker_model('reviewer') if offline else model,
        name='reviewer',
        capabilities=[Hooks(after_run=child_completed)],
        model_settings={'temperature': 0, 'max_tokens': 256},
        description='Review the explanation and identify where tools execute.',
        instructions='Return a concise checked explanation. Tools execute in the host, not in the model.',
    )
    agent = Agent(
        model,
        capabilities=[
            DynamicWorkflow(
                agents=[explainer, reviewer],
                max_agent_calls=2,
                sub_agent_usage_limits=UsageLimits(request_limit=6),
                resource_limits={'max_duration_secs': 5},
            )
        ],
        model_settings={'temperature': 0, 'max_tokens': 512},
    )
    # 断点：dynamic_workflow/_toolset.py 的 call_tool；核心 agent/abstract.py 的 run。
    async with agent:
        result = await agent.run(
            f'Call run_workflow exactly once with this code, then report its result:\n{WORKFLOW}',
            usage_limits=UsageLimits(request_limit=8, tool_calls_limit=4),
        )
    if completed_agents != {'explainer', 'reviewer'}:
        raise RuntimeError(f'实验未完成：成功子 Agent 为 {completed_agents!r}')
    return result


async def background(model: Model) -> AgentRunResult[str]:
    """后台任务等待普通工具的信号，直观看到模型能在任务未完成时继续调用工具."""
    independent_done = asyncio.Event()
    agent = Agent(model, capabilities=[BackgroundTools()], model_settings={'temperature': 0, 'max_tokens': 512})

    async def delayed_summary() -> str:
        """Start this once, then call independent_step while this work is pending."""
        # 用事件证明并发次序；上限只用于让错误的本地模型调用顺序及时结束。
        await asyncio.wait_for(independent_done.wait(), timeout=180)
        return 'background-complete: independent-step was completed before this result.'

    async def independent_step() -> str:
        """Perform independent work while delayed_summary is pending; call once."""
        independent_done.set()
        return 'independent-step-complete'

    agent.tool_plain(metadata={'background': True})(delayed_summary)
    agent.tool_plain(independent_step)
    # 断点：background_tools/_capability.py 的 wrap_tool_execute、after_node_run、_deliver。
    # run() 会等待并交付后台结果；这里不使用无法交付该结果的 run_stream()。
    async with agent:
        result = await agent.run(
            'First call delayed_summary once. After it starts, call independent_step once. '
            'Do not repeat or poll either tool. End your response when there is no independent work left; '
            'the agent will resume with the background result. Report that result when it arrives.',
            usage_limits=UsageLimits(request_limit=8, tool_calls_limit=4),
        )
    if not any(
        isinstance(part, UserPromptPart) and isinstance(part.content, str) and 'background-complete' in part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
    ):
        raise RuntimeError('实验未完成：后台结果没有交付给模型')
    return result


async def run_lesson(lesson: Lesson, *, offline: bool = False) -> AgentRunResult[str]:
    """默认仅使用本地 Ollama，环境变量与 main.py 相同."""
    if offline:
        calls = {
            'code-mode': [ToolCallPart('run_code', {'code': CODE})],
            'workflow': [ToolCallPart('run_workflow', {'code': WORKFLOW})],
            'background': [ToolCallPart('delayed_summary', {}), ToolCallPart('independent_step', {})],
        }
        model = scripted_model(calls[lesson])
    else:
        model = OpenAIChatModel(
            getenv('OLLAMA_MODEL', 'qwen2.5-harness:14b-16k'),
            provider=OllamaProvider(base_url=getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')),
        )
    if lesson == 'code-mode':
        return await code_mode(model)
    if lesson == 'workflow':
        return await workflow(model, offline=offline)
    return await background(model)


async def main() -> None:
    """选择一个实验，并打印实际调用与最终结果."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lesson', choices=['code-mode', 'workflow', 'background'], default='code-mode')
    parser.add_argument('--offline', action='store_true', help='固定模型决策，仍执行真实能力和工具')
    args = parser.parse_args()
    lesson: Lesson = args.lesson
    result = await run_lesson(lesson, offline=args.offline)
    for message in result.all_messages():
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    print(f'[工具调用] {part.tool_name}: {part.args_as_dict()}')
    print(result.output)
    print(f'[用量] {result.usage}')


if __name__ == '__main__':
    asyncio.run(main())
