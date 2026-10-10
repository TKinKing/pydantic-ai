"""只使用 Pydantic AI 核心的中文 Agent 示例；直接运行时依次展示五种运行入口."""

import asyncio  # 驱动异步运行入口。
from dataclasses import dataclass  # 应用依赖由代码提供，不交给模型生成。
from os import getenv  # 支持切换本地 Ollama 模型和地址。

from pydantic import BaseModel, Field  # 最终答案采用有类型的结构化输出。

from pydantic_ai import Agent, AgentRunResultEvent, ModelRetry, RunContext  # Agent 核心 API。
from pydantic_ai.capabilities import AbstractCapability  # capabilities（简称 caps）扩展运行生命周期。
from pydantic_ai.messages import ModelRequest, ToolReturnPart  # 检查教学工具是否真正执行并返回。
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel  # Ollama 提供 OpenAI 兼容接口。
from pydantic_ai.output import ToolOutput  # 用工具调用承载最终结构，适配本地模型。
from pydantic_ai.providers.ollama import OllamaProvider  # 连接本地 Ollama。
from pydantic_ai.toolsets import FunctionToolset  # 把一组可复用工具作为组件注册。
from pydantic_ai.usage import UsageLimits  # 限制一次运行的请求和工具调用。


@dataclass  # 应用通过 deps 传入事实，避免模型自行编造。
class LearningDeps:
    """应用注入的学习者身份."""

    learner: str = '中文学习者'  # 动态指令、工具和输出校验均可读取此身份。


class StudyNote(BaseModel):  # output_type 告诉 Agent 最终答案应符合这个结构。
    """经过验证的中文学习笔记."""

    topic: str = Field(description='本次学习的主题')  # 输出字段会成为模型可见的模式。
    summary: str = Field(description='包含 Agent 与工具关系的中文总结')  # 由校验器再检查业务要求。


class LearningCapability(AbstractCapability[LearningDeps]):
    """自定义 capability：观察运行开始及每次模型请求，不是模型调用的工具."""

    async def before_run(self, ctx: RunContext[LearningDeps]) -> None:
        print(f'[capability] 开始学习：{ctx.deps.learner}')

    async def before_model_request(
        self, ctx: RunContext[LearningDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        print(f'[capability] 模型请求；当前消息数：{len(ctx.messages)}')
        return request_context  # 返回请求上下文；需要时可在这里修改请求配置。


def build_agent(*, require_tools: bool = True) -> Agent[LearningDeps, StudyNote]:  # 流式模式允许先返回最终输出。
    """组装模型、指令、工具和输出校验器."""
    model = OpenAIChatModel(  # 使用本机已安装且支持工具调用的模型。
        getenv('OLLAMA_MODEL', 'qwen2.5:14b-instruct-q4_K_M'),
        provider=OllamaProvider(base_url=getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')),
    )
    study_tools = FunctionToolset[LearningDeps]()

    def study_checklist() -> list[str]:
        """获取学习检查清单，在提交笔记前调用."""
        print('[toolset] 执行 study_checklist')
        return ['解释 Agent 管理执行循环', '解释工具由应用执行', '计算学习进度']

    study_tools.tool_plain(study_checklist)  # ??????????????
    agent = Agent(  # 泛型参数让 deps 和最终输出在 IDE 中保持类型安全。
        model,
        name='learning_agent',
        deps_type=LearningDeps,
        output_type=ToolOutput(StudyNote),
        toolsets=[study_tools],
        capabilities=[LearningCapability()],
        model_settings={'temperature': 0.2},  # 默认模型设置，也可在单次 run 中覆盖。
        instructions=(
            '用中文教学。先调用 study_checklist 和概念工具，再用进度工具计算 1/2，最后返回简短学习笔记。'
            if require_tools
            else '在 Pydantic AI 中，Agent 管理模型请求和工具执行；工具是应用注册的 Python 函数。用中文简短解释并返回结构化笔记。'
        ),
        retries=4,  # 本地模型可能先尝试直接返回结果，给它机会改用工具。
    )

    def learner_instruction(ctx: RunContext[LearningDeps]) -> str:
        """把学习者身份加入当前请求."""
        return f'学习者：{ctx.deps.learner}。总结中写清 Agent 与工具的关系。'

    def explain_concept(concept: str) -> str:
        """解释 Agent 或工具；concept 只能是 Agent 或 工具."""
        print(f'[tool_plain] 执行 explain_concept：{concept}')
        if concept == 'Agent':
            return 'Agent 管理模型请求、工具调用和最终输出的执行循环。'
        if concept == '工具':
            return '工具是应用注册的 Python 函数；模型提出调用，Agent 执行并返回结果。'
        raise ModelRetry('concept 请使用 Agent 或 工具。')  # 错误返回模型，让它修正参数。

    def learning_progress(ctx: RunContext[LearningDeps], completed: int, total: int) -> str:
        """计算学习进度；completed 是完成数，total 是总数."""
        print(f'[tool] 执行 learning_progress：{completed}/{total}')
        if total <= 0 or not 0 <= completed <= total:
            raise ModelRetry('请满足 total > 0 且 0 <= completed <= total。')
        return f'{ctx.deps.learner}已完成 {completed}/{total}，进度 {completed / total:.0%}。'

    def validate_note(ctx: RunContext[LearningDeps], note: StudyNote) -> StudyNote:
        """检查中文总结是否覆盖两个核心概念."""
        if ctx.partial_output:  # run_stream 可能对尚未完成的输出调用校验器。
            return note
        completed = {
            part.tool_name
            for message in ctx.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        if require_tools and not {'study_checklist', 'explain_concept', 'learning_progress'} <= completed:
            raise ModelRetry('先调用 study_checklist、explain_concept 和 learning_progress，再提交最终学习笔记。')
        if require_tools and not any(
            part.tool_name == 'learning_progress' and isinstance(part.content, str) and '1/2' in part.content
            for message in ctx.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ):
            raise ModelRetry('请用 learning_progress 计算 completed=1、total=2，然后再提交笔记。')
        if 'Agent' not in note.summary or '工具' not in note.summary:
            raise ModelRetry('总结中请同时说明 Agent 和工具的关系。')
        return note

    agent.instructions(learner_instruction)  # ??? @agent.instructions?
    agent.tool_plain(explain_concept)  # ??? @agent.tool_plain????????
    agent.tool(learning_progress)  # ??? @agent.tool????????
    agent.output_validator(validate_note)  # ??? @agent.output_validator?
    return agent


def run_sync(agent: Agent[LearningDeps, StudyNote], deps: LearningDeps) -> None:
    """第一个示例：同步跑完工具调用和输出校验，方便设置断点."""
    result = agent.run_sync(
        '请调用 study_checklist，解释 Agent 和工具，用 learning_progress 计算 completed=1、total=2，再提交笔记。',
        deps=deps,
        usage_limits=UsageLimits(request_limit=8, tool_calls_limit=8),
    )
    print('同步结果：', result.output.model_dump())
    print(f'同步请求数：{result.usage.requests}；工具调用数：{result.usage.tool_calls}')


async def run_normal(agent: Agent[LearningDeps, StudyNote], deps: LearningDeps) -> None:
    """演示完整运行、结构化输出和消息历史续接."""
    first = await agent.run(  # run 返回完整结果，包括输出、用量和消息。
        '请解释 Agent 和工具，调用 learning_progress 计算 completed=1、total=2，再写中文学习笔记。',
        deps=deps,
        usage_limits=UsageLimits(request_limit=8, tool_calls_limit=8),
    )
    print('结构化输出：', first.output.model_dump())  # StudyNote 已经通过结构和业务校验。
    print(f'首次请求数：{first.usage.requests}；消息数：{len(first.all_messages())}')
    print(
        '已执行工具：',
        [
            part.tool_name
            for message in first.all_messages()
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ],
    )
    followup = Agent[LearningDeps, str](  # 续问只需要短文本，不再强制提交结构化学习笔记。
        agent.model, deps_type=LearningDeps, instructions='用中文简短回答，不调用工具。'
    )
    second = await followup.run(  # 把上一轮消息传给模型，继续同一段对话。
        '沿用刚才的话题，换一句话概括。',
        deps=deps,
        message_history=first.all_messages(),
        usage_limits=UsageLimits(request_limit=8, tool_calls_limit=8),
    )
    print('继续对话：', second.output)
    print(f'本轮新消息数：{len(second.new_messages())}')  # 与包含旧历史的 all_messages() 区分。


async def run_stream(agent: Agent[LearningDeps, StudyNote], deps: LearningDeps) -> None:
    """演示流式结构化输出."""
    async with agent.run_stream('解释 Agent 和工具并总结。', deps=deps) as result:
        async for note in result.stream_output():  # 结构化输出更新时逐次收到 StudyNote。
            print('流式更新：', note.model_dump())
        print('流式最终结果：', (await result.get_output()).model_dump())


async def run_events(agent: Agent[LearningDeps, StudyNote], deps: LearningDeps) -> None:
    """演示运行事件流."""
    counts: dict[str, int] = {}  # 聚合频繁的 token 增量事件，保持终端可读。
    async with agent.run_stream_events('解释 Agent 和工具并总结。', deps=deps) as events:
        async for event in events:  # 工具、模型输出和最终结果都从事件流中观察。
            if isinstance(event, AgentRunResultEvent):
                print('事件流最终结果：', event.result.output.model_dump())
            else:
                name = type(event).__name__
                counts[name] = counts.get(name, 0) + 1
    print('事件类型与次数：', counts)


async def run_steps(agent: Agent[LearningDeps, StudyNote], deps: LearningDeps) -> None:
    """演示逐步遍历 Agent 图节点."""
    async with agent.iter('解释 Agent 和工具并总结。', deps=deps) as agent_run:
        async for node in agent_run:  # 逐个观察 Agent 图中的节点。
            print('节点：', type(node).__name__)
        assert agent_run.result is not None  # 遍历结束后才有最终结果。
        print('逐步运行结果：', agent_run.result.output.model_dump())


async def main() -> None:  # 固定顺序执行异步示例，无需命令行参数。
    """依次展示普通运行、结构化流式输出、事件流和逐步执行."""
    deps = LearningDeps()
    await run_normal(build_agent(require_tools=True), deps)  # 验证三个工具的真实执行。
    agent = build_agent(require_tools=False)  # 流式演示聚焦观察输出，不强制先调用工具。
    await run_stream(agent, deps)
    await run_events(agent, deps)
    await run_steps(agent, deps)


if __name__ == '__main__':
    run_sync(build_agent(require_tools=True), LearningDeps())  # 同步入口在异步事件循环启动前执行。
    asyncio.run(main())
