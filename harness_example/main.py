"""DeepSeek / 本地 Ollama 的完整 Harness 学习流程：python -m harness_example.main."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from os import name as platform_name
from pathlib import Path

from pydantic_ai import Agent, AgentRunResult, ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability, Hooks, PrepareTools, ValidatedToolArgs
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model, ModelRequestContext
from pydantic_ai.settings import ModelSettings, ToolOrOutput
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import (
    AskUser,
    ClampOversizedMessages,
    ClearToolResults,
    ConversationSearch,
    FileSystem,
    GuardrailResult,
    InputGuardrail,
    Memory,
    OutputGuardrail,
    Planning,
    RepoContext,
    ReportContextUsage,
    Skills,
    SlidingWindowCompaction,
    StepPersistence,
    SubAgent,
    SubAgents,
    SystemReminders,
    ToolGuardrail,
    ToolOutputLimits,
    WarnNearLimits,
)
from pydantic_ai_harness.ask_user import AskUserAnswer, AskUserRequest, AskUserResponse
from pydantic_ai_harness.compaction import ContextUsageEvent
from pydantic_ai_harness.conversation_search import SnapshotHistorySource
from pydantic_ai_harness.guardrails import InputBlocked, ToolCallInfo
from pydantic_ai_harness.memory import FileStore
from pydantic_ai_harness.planning import PlanItem, SqlitePlanStore, TaskStatus
from pydantic_ai_harness.step_persistence import FileStepStore, continue_run
from pydantic_ai_harness.subagents import DelegationEndEvent
from pydantic_ai_harness.system_reminders import Reminder
from pydantic_ai_harness.tool_output_limits import Band, Truncate

if __package__:
    from .local_workspace import create_local_workspace, create_shell
    from .mcp_client import create_mcp_capability
    from .memory_history import demonstrate_history, demonstrate_memory
    from .model_config import create_model
    from .rag import InMemoryRetrievalService, KnowledgeRAG, RetrievalService
    from .tool_descriptions import TOOL_DESCRIPTIONS
else:
    from local_workspace import create_local_workspace, create_shell
    from mcp_client import create_mcp_capability
    from memory_history import demonstrate_history, demonstrate_memory
    from model_config import create_model
    from rag import InMemoryRetrievalService, KnowledgeRAG, RetrievalService
    from tool_descriptions import TOOL_DESCRIPTIONS

WORKSPACE = Path(__file__).resolve().parent / 'output' / 'demo'
REQUEST_LIMIT = 40


@dataclass(frozen=True)
class LessonStep:
    """只规定学习目标和本步工具；调用参数仍由模型生成."""

    tool: str
    instruction: str
    required_argument: tuple[str, str] | None = None
    plan_status: TaskStatus | None = None


LESSON_STEPS = (
    LessonStep('write_plan', '创建一项计划：学习 Harness 并写总结，status=in_progress。'),
    LessonStep('list_directory', '列出当前目录，path="."。', ('path', '.')),
    LessonStep('read_file', '读取 lesson.txt。', ('path', 'lesson.txt')),
    LessonStep('load_capability', '加载 study-notes 技能，id="study-notes"。', ('id', 'study-notes')),
    LessonStep('search_knowledge', '检索外部知识，query="Harness"；记录结果中的来源。', ('query', 'Harness')),
    LessonStep('mcp_add', '通过 MCP 服务计算 7 加 5，a=7、b=5。'),
    LessonStep(
        'ask_user_question',
        '询问学习方式，只问一个问题，提供两个选项。参数形状：'
        '{"questions":[{"header":"学习方式","question":"想怎样学习？",'
        '"options":[{"label":"先看例子"},{"label":"先看概念"}]}]}。',
    ),
    LessonStep('learning_progress', '计算学习进度，completed=2、total=3。'),
    LessonStep('run_command', '执行 echo harness-demo。', ('command', 'echo harness-demo')),
    LessonStep('long_reference', '读取长参考资料，观察工具输出截断。'),
    LessonStep(
        'delegate_task',
        '请 reviewer 审阅：Agent 管循环，Harness 提供可选工具、指令和钩子。任务放在 task 参数。',
        ('agent_name', 'reviewer'),
    ),
    LessonStep('write_memory', '保存一条包含 Harness 的中文学习结论到 MEMORY.md。'),
    LessonStep('read_memory', '读回 MEMORY.md。', ('file', 'MEMORY.md')),
    LessonStep('search_memory', '搜索长期笔记，query="Harness"。', ('query', 'Harness')),
    LessonStep('search_conversation_history', '搜索已保存的对话历史，query="Harness"。', ('query', 'Harness')),
    LessonStep('write_file', '把中文学习总结写入 report.md，content 自己归纳。', ('path', 'report.md')),
    LessonStep('write_plan', '把计划整表更新为一项已完成任务，status=completed。', plan_status=TaskStatus.completed),
    LessonStep('read_plan', '读回已完成的计划。'),
)


@dataclass
class LearningDeps:
    """应用状态通过 ctx.deps 注入，不让模型填写用户身份或完成记录."""

    learner: str = '中文学习者'
    user_id: str = 'learner-001'
    retrieval: RetrievalService = field(default_factory=InMemoryRetrievalService)
    tools: dict[str, ToolDefinition] = field(default_factory=dict[str, ToolDefinition])
    completed_steps: list[str] = field(default_factory=list[str])
    completed_tools: list[str] = field(default_factory=list[str])
    context_events: int = 0
    successful_delegations: int = 0
    continuing: bool = False


@dataclass
class Walkthrough(AbstractCapability[LearningDeps]):
    """用公开钩子观察真实执行；guided 模式让每个主要工具都有断点机会."""

    guided: bool = True

    def get_instructions(self) -> Callable[[RunContext[LearningDeps]], str]:
        def instructions(ctx: RunContext[LearningDeps]) -> str:
            if ctx.deps.continuing:
                return '这是从磁盘快照恢复后的新运行。只用已有历史写一段中文总结，不再调用工具。'
            if self.guided and len(ctx.deps.completed_steps) < len(LESSON_STEPS):
                step = LESSON_STEPS[len(ctx.deps.completed_steps)]
                return (
                    f'当前教学步骤 {len(ctx.deps.completed_steps) + 1}/{len(LESSON_STEPS)}：'
                    f'调用 {step.tool}，{step.instruction}'
                    '必须发出真实工具调用，不能用正文模拟。只完成当前步骤，后续步骤由下一轮指令给出。'
                )
            return '学习工具流程已经结束，请用中文给出包含“总结”的最终回答。' if self.guided else ''

        return instructions

    def get_model_settings(self) -> Callable[[RunContext[LearningDeps]], ModelSettings]:
        def settings(ctx: RunContext[LearningDeps]) -> ModelSettings:
            if ctx.deps.continuing or (self.guided and len(ctx.deps.completed_steps) == len(LESSON_STEPS)):
                return {'tool_choice': ToolOrOutput([])}
            if self.guided:
                step = LESSON_STEPS[len(ctx.deps.completed_steps)]
                return {'tool_choice': ToolOrOutput([step.tool]), 'parallel_tool_calls': False}
            return {}

        return settings

    async def before_tool_execute(
        self,
        ctx: RunContext[LearningDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        if self.guided and not ctx.deps.continuing and len(ctx.deps.completed_steps) < len(LESSON_STEPS):
            step = LESSON_STEPS[len(ctx.deps.completed_steps)]
            if call.tool_name != step.tool:
                raise ModelRetry(f'当前步骤只调用 {step.tool}。')
            if step.required_argument is not None:
                name, value = step.required_argument
                if args.get(name) != value:
                    raise ModelRetry(f'本步要求 {name}={value!r}。{step.instruction}')
            if step.plan_status is not None:
                items: list[PlanItem] = args['items']  # Planning 已将参数校验为公开的 PlanItem 类型。
                if not items or any(item.status is not step.plan_status for item in items):
                    raise ModelRetry(f'本步要求非空计划，所有任务 status={step.plan_status.value!r}。')
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[LearningDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: object,
    ) -> object:
        # 校验失败、工具异常或护栏拒绝不会到达此钩子。
        if call.tool_name == 'delegate_task' and not ctx.deps.successful_delegations:
            raise ModelRetry('审阅子代理尚未成功完成，请重新委派。')
        ctx.deps.completed_tools.append(call.tool_name)
        if self.guided and not ctx.deps.continuing and len(ctx.deps.completed_steps) < len(LESSON_STEPS):
            step = LESSON_STEPS[len(ctx.deps.completed_steps)]
            if call.tool_name == step.tool:
                ctx.deps.completed_steps.append(step.tool)
        return result


async def chinese_tools(ctx: RunContext[LearningDeps], tools: list[ToolDefinition]) -> list[ToolDefinition]:
    """只替换描述，保留工具参数模式和原始行为."""
    translated = [replace(tool, description=TOOL_DESCRIPTIONS.get(tool.name, tool.description)) for tool in tools]
    ctx.deps.tools.update({tool.name: tool for tool in translated})
    return translated


def input_guard(prompt: str) -> GuardrailResult:
    """示范业务输入校验，不是通用提示注入检测器."""
    if '示例禁止' in prompt:
        # 终止运行，避免合成拒绝文本又被教学输出校验重试。
        raise InputBlocked('输入包含本例的禁用标记。')
    return GuardrailResult.allow()


def output_guard(output: object) -> GuardrailResult:
    """最终输出校验，不合格时要求模型重试."""
    if not isinstance(output, str) or '总结' not in output:
        return GuardrailResult.retry('请用中文回答，并包含“总结”二字。')
    return GuardrailResult.allow()


def tool_guard(call: ToolCallInfo) -> GuardrailResult:
    """文件工具还会执行自身的路径检查."""
    if call.name == 'delete_memory' or (call.name == 'write_file' and call.args.get('path') != 'report.md'):
        return GuardrailResult.block('本例只允许写 report.md，并保留所有学习记忆。')
    return GuardrailResult.allow()


def prepare_workspace(workspace: Path) -> None:
    """准备模型可以读取的资料；报告由模型调用 FileSystem 写入."""
    skill_dir = workspace / 'skills' / 'study-notes'
    skill_dir.mkdir(parents=True, exist_ok=True)
    (workspace / 'lesson.txt').write_text('Agent 管执行循环。Harness 提供计划、工具、记忆和钩子。\n', encoding='utf-8')
    (workspace / 'AGENTS.md').write_text('请用中文回答。只把学习报告写入 report.md。\n', encoding='utf-8')
    (skill_dir / 'SKILL.md').write_text(
        '---\nname: study-notes\ndescription: 用中文整理 Harness 学习笔记。\n---\n'
        '读取 lesson.txt；区分核心与 Harness；检查概念后写报告、保存记忆并完成计划。\n',
        encoding='utf-8',
    )


def build_agent(
    *,
    workspace: Path = WORKSPACE,
    model: Model | None = None,
    reviewer_model: Model | None = None,
    guided: bool = True,
) -> tuple[Agent[LearningDeps, str], FileStepStore]:
    """组合内置能力、自定义 RAG 和 MCP；测试只替换 Model，不替换工具."""
    store = FileStepStore(workspace / 'steps')
    if model is None:
        model = create_model()
    reviewer = Agent(
        reviewer_model or model,
        name='reviewer',
        instructions='用中文检查任务中的概念是否正确，只返回简短意见。',
        model_settings={'temperature': 0.2, 'max_tokens': 256},
    )

    async def answer_user(request: AskUserRequest) -> AskUserResponse:
        """固定选第一项；这是模拟学习偏好，真实交互版见 pydantic_harness_example."""
        answers: list[AskUserAnswer] = []
        for question in request.questions:
            answers.append(AskUserAnswer(header=question.header, selected=(question.options[0].label,)))
        return AskUserResponse(answers=tuple(answers))

    async def guide_current_step(
        ctx: RunContext[LearningDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """在本次请求末尾强调真实工具调用，不把提醒写入持久历史."""
        if guided and not ctx.deps.continuing and len(ctx.deps.completed_steps) < len(LESSON_STEPS):
            step = LESSON_STEPS[len(ctx.deps.completed_steps)]
            reminder = (
                f'[harness-learning-step] 当前必须实际执行第 {len(ctx.deps.completed_steps) + 1} 步：'
                f'调用工具 {step.tool}。{step.instruction}'
                '程序尚未记录这一步成功。即使记忆或历史中已有相关内容，也需要真正调用当前工具。'
                '现在只发送这一个工具调用，不要输出确认文字，不要声称已经执行。'
            )
            # 只影响本次请求；不 append 到 ctx.messages，避免提醒在历史和快照中累积。
            return replace(
                request_context,
                messages=[*request_context.messages, ModelRequest(parts=[UserPromptPart(reminder)])],
            )
        return request_context

    agent = Agent(
        model,
        name='harness_learning',
        deps_type=LearningDeps,
        instructions='用中文学习 Harness：读取 lesson.txt，加载 study-notes 技能，制定计划并执行。最终给出总结。',
        model_settings={'temperature': 0.2, 'max_tokens': 1024},
        # 本地模型可能在步骤间先输出确认文字；输出重试是整次 run 的累计预算。
        retries={'tools': 8, 'output': len(LESSON_STEPS) + 2 if guided else 8},
        capabilities=[
            create_local_workspace(workspace),  # Windows 原生适配；POSIX 使用内置 LocalWorkspace。
            Walkthrough(guided=guided),  # 自定义教学能力，不计入内置 Harness 能力。
            InputGuardrail(guard=input_guard),
            StepPersistence(store=store),
            ClampOversizedMessages(max_part_chars=12_000),
            ClearToolResults(max_messages=12, keep_pairs=3, placeholder='[旧工具结果已清理，可搜索历史]'),
            SlidingWindowCompaction(max_messages=24, keep_messages=16),
            Memory(FileStore('memory'), namespace=lambda ctx: ctx.deps.user_id, max_tokens=600),
            FileSystem(tools=['read_file', 'write_file', 'list_directory'], content_hashes=False),
            create_shell(),  # Windows 使用原生 echo 教学工具；POSIX 使用 Harness Shell。
            RepoContext(),
            Skills('skills'),
            KnowledgeRAG(),  # 自定义能力：工具通过 deps 调用应用提供的检索服务。
            create_mcp_capability(),  # 核心 MCP 能力：启动并连接独立的 stdio 服务进程。
            Planning(store=SqlitePlanStore(str(workspace / 'plan.db')), tools=['write_plan', 'read_plan']),
            SystemReminders(reminders=[Reminder('保持中文解释，完成后更新计划并给出总结。', interval=4)]),
            AskUser(answerer=answer_user),
            SubAgents(agents=[SubAgent(reviewer, description='检查学习总结的概念', max_calls=3)], max_depth=2),
            ConversationSearch(SnapshotHistorySource(store), scope='conversation'),
            ToolGuardrail(guard=tool_guard),
            ToolOutputLimits(per_tool={'long_reference': [Band(over=500, action=Truncate(max_chars=350))]}),
            # 接近硬预算才提示收尾，避免教学流程中途收到减少工具调用的竞争指令。
            WarnNearLimits(max_iterations=REQUEST_LIMIT, warning_threshold=0.8),
            ReportContextUsage(context_window=1_000_000 if model.system == 'deepseek' else 16_384),
            OutputGuardrail(guard=output_guard),
            PrepareTools(chinese_tools),
            Hooks(before_model_request=guide_current_step),  # 当前步骤位于记忆、计划和提醒之后。
        ],
    )

    def learning_progress(ctx: RunContext[LearningDeps], completed: int, total: int) -> str:
        """计算学习进度；ctx 提供应用身份，模型只提供 completed 和 total."""
        if total <= 0 or not 0 <= completed <= total:
            raise ModelRetry('请满足 total > 0 且 0 <= completed <= total。')
        return f'{ctx.deps.learner}：已完成 {completed}/{total}，进度 {completed / total:.0%}。'

    def long_reference() -> str:
        """返回长参考资料，实际触发 ToolOutputLimits."""
        return 'Agent 管理执行循环；Harness 能力组合工具、指令和生命周期钩子。\n' * 100

    def validate_completion(ctx: RunContext[LearningDeps], output: str) -> str:
        if guided and len(ctx.deps.completed_steps) < len(LESSON_STEPS):
            step = LESSON_STEPS[len(ctx.deps.completed_steps)]
            raise ModelRetry(f'学习流程尚未完成，请调用 {step.tool}。{step.instruction}')
        return output

    async def record_context(ctx: RunContext[LearningDeps], event: ContextUsageEvent) -> None:
        ctx.deps.context_events += 1

    async def record_delegation(ctx: RunContext[LearningDeps], event: DelegationEndEvent) -> None:
        if event.outcome == 'ok':
            ctx.deps.successful_delegations += 1

    agent.tool(learning_progress)
    agent.tool_plain(long_reference)
    agent.output_validator(validate_completion)
    agent.on_event(ContextUsageEvent)(record_context)
    agent.on_event(DelegationEndEvent)(record_delegation)
    return agent, store


async def run_example(
    *,
    workspace: Path = WORKSPACE,
    model: Model | None = None,
    reviewer_model: Model | None = None,
    retrieval: RetrievalService | None = None,
    guided: bool = True,
    resume: bool = True,
) -> AgentRunResult[str]:
    """运行、保存证据，再从磁盘快照发起真正的下一轮模型请求."""
    prepare_workspace(workspace)
    agent, store = build_agent(workspace=workspace, model=model, reviewer_model=reviewer_model, guided=guided)
    deps = LearningDeps()
    if retrieval is not None:
        deps.retrieval = retrieval
    limits = UsageLimits(request_limit=REQUEST_LIMIT, tool_calls_limit=32)
    async with agent:
        result = await agent.run(
            '学习 Harness，完成资料阅读、计划、提问、审阅、记忆和 report.md，并给出总结。',
            deps=deps,
            usage_limits=limits,
        )
        (workspace / 'messages.json').write_bytes(result.all_messages_json())
        runs = await store.list_runs(conversation_id=result.conversation_id)
        history = await continue_run(store, run_id=runs[-1].run_id)
        if resume:
            deps.continuing = True
            result = await agent.run(
                '请根据刚才的历史，用一段中文总结你已经完成的工作，不重复执行工具。',
                message_history=history,
                conversation_id=result.conversation_id,
                usage=result.usage,
                deps=deps,
                usage_limits=limits,
            )
            (workspace / 'continued_messages.json').write_bytes(result.all_messages_json())
    definitions = {
        name: {'说明': tool.description, '参数模式': tool.parameters_json_schema} for name, tool in deps.tools.items()
    }
    (workspace / 'tools.json').write_text(json.dumps(definitions, ensure_ascii=False, indent=2), encoding='utf-8')
    evidence = {
        'guided': guided,
        'required_steps': [step.tool for step in LESSON_STEPS],
        'completed_steps': deps.completed_steps,
        'completed_tools': deps.completed_tools,
        'context_events': deps.context_events,
        'successful_delegations': deps.successful_delegations,
        'continued_from_snapshot': resume,
        'registered_harness_capabilities': 19 if platform_name == 'nt' else 20,
        'extensions': ['KnowledgeRAG', 'MCP', *(['NativeWorkspace', 'NativeShell'] if platform_name == 'nt' else [])],
        'note': '工具成功返回与能力注册分别记录；不代表每个护栏拒绝或压缩分支都已触发。',
    }
    (workspace / 'coverage.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


async def main() -> None:
    """根据 API Key 选择模型，逐步执行完整流程并从快照续接."""
    model = create_model()
    await run_example(model=model)
    study_workspace = WORKSPACE.parent / 'memory-history'
    await demonstrate_memory(workspace=study_workspace, model=model)
    await demonstrate_history(workspace=study_workspace, model=model)


if __name__ == '__main__':
    asyncio.run(main())
