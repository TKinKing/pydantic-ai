"""通过本地 Ollama 交互演示普通工具、延迟工具和 capability."""

import asyncio
from dataclasses import dataclass
from os import getenv
from typing import Any, Literal

from pydantic_ai import Agent, AgentRunResult, CallDeferred, DeferredToolRequests, ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.usage import UsageLimits


@dataclass
class LearningDeps:
    """应用通过 deps 提供给工具和 capability 的学习者信息."""

    learner: str = '中文学习者'
    concept_explained: bool = False
    answers_received: int = 0


class LearningCapability(AbstractCapability[LearningDeps]):
    """观察每次运行及模型请求；capability 钩子由框架调用，不是模型工具."""

    async def wrap_run(self, ctx: RunContext[LearningDeps], *, handler: WrapRunHandler) -> AgentRunResult[Any]:
        print('[cap.wrap_run] 进入：即将执行 handler()')
        try:
            return await handler()
        finally:
            print('[cap.wrap_run] 退出：handler() 已结束或抛出异常')

    async def before_run(self, ctx: RunContext[LearningDeps]) -> None:
        print(f'[cap.before_run] 学习者：{ctx.deps.learner}；run_id={ctx.run_id}')

    async def before_model_request(
        self, ctx: RunContext[LearningDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        print(f'[cap.before_model_request] 第 {ctx.run_step} 步；当前消息数：{len(ctx.messages)}')
        return request_context

    async def after_run(self, ctx: RunContext[LearningDeps], *, result: AgentRunResult[Any]) -> AgentRunResult[Any]:
        status = '暂停，等待用户回答' if isinstance(result.output, DeferredToolRequests) else '已生成最终答案'
        print(f'[cap.after_run] {status}')
        return result


def build_agent() -> Agent[LearningDeps, str | DeferredToolRequests]:
    """创建带普通工具、延迟工具和 capability 的交互 Agent."""
    model = OpenAIChatModel(
        getenv('OLLAMA_MODEL', 'qwen2.5:14b-instruct-q4_K_M'),
        provider=OllamaProvider(base_url=getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')),
    )
    agent = Agent(
        model,
        name='learning_agent',
        deps_type=LearningDeps,
        output_type=[str, DeferredToolRequests],
        instructions=(
            '你是 Pydantic AI 源码学习助手，用中文回答。'
            '先调用 explain_concept 获取与用户问题最相关的概念。'
            '如果消息历史里还没有 ask_learner 的工具返回结果，必须调用 ask_learner，'
            '针对用户原问题提出一个简短的澄清问题，例如希望看业务例子还是内部执行顺序。'
            '每个原问题只追问一次；不要把追问直接作为最终文本输出。'
            '如果历史里已有 ask_learner 的返回结果，那就是用户的回答：'
            '结合原问题、用户回答和概念工具结果，直接给出简明解释和小例子，不再追问。'
            '代码例子使用 Agent、agent.tool 等公开 API，说明模型提出调用、框架执行 Python 函数的区别。'
            '解释本例 ask_learner 时保留 CallDeferred 与 DeferredToolResults 的暂停/恢复含义，不编造用户回答。'
        ),
        capabilities=[LearningCapability()],
        model_settings={'temperature': 0.2},
        retries=4,
    )

    def explain_concept(
        ctx: RunContext[LearningDeps], concept: Literal['Agent', '工具', 'capability', '延迟工具', '图']
    ) -> str:
        """查询核心概念，演示带 RunContext 的普通工具."""
        print(f'[tool] explain_concept({concept!r})；deps.learner={ctx.deps.learner!r}')
        explanations = {
            'Agent': 'Agent 负责组织模型请求、工具调用、重试和最终输出的执行循环。',
            '工具': (
                '工具注册时不会执行。模型返回工具名和参数后，框架校验参数、调用已注册的 Python 函数，'
                '再把 ToolReturnPart 结果交回模型。应用不需要自己直接调用这个函数。'
            ),
            'capability': 'Capability 通过生命周期钩子扩展运行行为，由框架调用而不是由模型选择。',
            '延迟工具': '工具抛出 CallDeferred 后，本次运行返回 DeferredToolRequests；应用提供结果后启动新运行续接。',
            '图': 'Graph 描述节点和连接；GraphRun 保存一次图运行；AgentRun 包装它，提供 Agent 的运行接口。',
        }
        ctx.deps.concept_explained = True
        return explanations[concept]

    def ask_learner(question: str) -> str:
        """向用户提问；应用收集回答后再通过 DeferredToolResults 恢复运行."""
        print(f'[deferred tool] ask_learner({question!r})')
        raise CallDeferred(metadata={'interaction': 'ask_learner'})

    def validate_answer(
        ctx: RunContext[LearningDeps], output: str | DeferredToolRequests
    ) -> str | DeferredToolRequests:
        # 让模型确实走过两个工具，避免只注册了工具却直接回答。
        if isinstance(output, str):
            if not ctx.deps.concept_explained:
                print('[output_validator] 缺少普通工具结果，请模型重试。')
                raise ModelRetry('请先调用 explain_concept 查询概念，再完成追问和最终回答。')
            if not ctx.deps.answers_received:
                print('[output_validator] 尚未取得用户回答，请模型调用延迟工具追问。')
                raise ModelRetry('请调用 ask_learner 向用户追问；收到它的工具结果后才能给最终答案。')
        return output

    # 注册函数；模型提出调用后，框架才执行对应工具。
    agent.tool(explain_concept)
    agent.tool_plain(ask_learner)
    agent.output_validator(validate_answer)
    return agent


def read_answer(prompt: str) -> str:
    """在终端读取非空输入；暂停后的输入由应用收集，不在工具函数里阻塞."""
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        print('输入不能为空，请重新输入。')


async def run_interactive(
    agent: Agent[LearningDeps, str | DeferredToolRequests], deps: LearningDeps
) -> AgentRunResult[str | DeferredToolRequests]:
    """运行模型提问、用户回答、模型继续生成答案的暂停/恢复流程."""
    user_question = read_answer('你想了解什么？（例如：Agent 是怎么调用工具的？）\n你：')
    # conversation 会带上累计用量，恢复运行也受同一份预算限制。
    limits = UsageLimits(request_limit=12, tool_calls_limit=12)

    # 断点 1：第一次 run，输入是用户原问题。
    result = await agent.run(
        user_question,
        deps=deps,
        usage_limits=limits,
    )

    # 断点 2：CallDeferred 让本次 run 结束；此时尚未得到最终文本。
    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        if not requests.calls:
            raise RuntimeError('运行暂停了，但没有可交给用户处理的延迟工具调用。')

        print('\n[应用] Agent 已暂停，接下来由终端收集用户回答。')
        answers: dict[str, str] = {}
        for call in requests.calls:
            if call.tool_name != 'ask_learner':
                raise RuntimeError(f'没有处理工具 {call.tool_name!r} 的延迟调用。')
            # 模型的工具参数可能是 JSON 字符串，也可能已经是字典。
            question = call.args_as_dict(raise_if_invalid=True).get('question')
            if not isinstance(question, str) or not question.strip():
                raise RuntimeError(f'ask_learner 的参数格式无效：{call.args!r}')

            answers[call.tool_call_id] = read_answer(f'\nLLM 追问：{question}\n你的回答：')
            deps.answers_received += 1

        # 断点 3：key 必须是 tool_call_id；用户回答会成为 ask_learner 的工具返回值。
        deferred_results = requests.build_results(calls=answers)
        conversation = result.conversation  # 携带消息历史、累计用量和同一个 conversation_id。
        print('[应用] 携带 conversation 和 DeferredToolResults，启动下一次 run。')
        result = await agent.run(
            conversation=conversation,
            deps=deps,
            deferred_tool_results=deferred_results,
            usage_limits=limits,
        )

    # 断点 4：all_messages() 包含追问前后的历史，new_messages() 只取恢复这次运行的新消息。
    print(f'\n最终答案：\n{result.output}')
    print(f'\n累计模型请求数：{result.usage.requests}；成功返回的工具调用数：{result.usage.tool_calls}')
    return result


async def main() -> None:
    """启动交互式学习示例."""
    async with build_agent() as agent:
        await run_interactive(agent, LearningDeps())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print('\n已退出交互。')
