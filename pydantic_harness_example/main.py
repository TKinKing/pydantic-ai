"""用本地 Ollama 运行可切换的 Harness 组合：python -m pydantic_harness_example.main."""

import argparse
import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic_agent_example.main import LearningCapability, LearningDeps, read_answer
from pydantic_ai import Agent, AgentRunResult, DeferredToolRequests, ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings, ToolOrOutput
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import AskUser, Coder, Memory, Planning, StepPersistence, SystemReminders
from pydantic_ai_harness.ask_user import (
    TOOL_NAME,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
    ask_user_result,
)
from pydantic_ai_harness.compaction import ClearToolResults, SlidingWindowCompaction, WarnNearLimits
from pydantic_ai_harness.memory import InMemoryStore
from pydantic_ai_harness.planning import InMemoryPlanStore
from pydantic_ai_harness.step_persistence import InMemoryStepStore
from pydantic_ai_harness.system_reminders import Reminder


class LearningFlow(LearningCapability):
    """把教学步骤转换为每次请求的工具选择，避免依赖模型自行遵守顺序."""

    def get_instructions(self) -> Callable[[RunContext[LearningDeps]], str]:
        def current_step(ctx: RunContext[LearningDeps]) -> str:
            if not ctx.deps.concept_explained:
                return (
                    '当前教学步骤：调用 explain_concept 工具。'
                    'concept 必须是 Agent、capability、组合、暂停恢复中的一个。'
                    '请发起真正的工具调用，不要输出解释或用正文模拟调用。'
                )
            if not ctx.deps.answers_received:
                return (
                    '当前教学步骤：调用 ask_user_question 工具询问用户想看什么。'
                    '参数示例：{"questions":[{"header":"学习方向","question":"你想看哪种解释？",'
                    '"options":[{"label":"业务例子"},{"label":"内部顺序"}],"multi_select":false}]}。'
                    '请发起真正的工具调用，不要用正文模拟调用，也不要替用户回答。'
                )
            return '用户已经回答。直接结合工具结果给出中文解释；不要再次追问，不要输出工具调用标记。'

        return current_step

    def get_model_settings(self) -> Callable[[RunContext[LearningDeps]], ModelSettings]:
        def select_tools(ctx: RunContext[LearningDeps]) -> ModelSettings:
            if not ctx.deps.concept_explained:
                return {'tool_choice': ToolOrOutput(['explain_concept'])}
            if not ctx.deps.answers_received:
                return {'tool_choice': ToolOrOutput([TOOL_NAME])}
            return {'tool_choice': 'auto'}

        return select_tools


@dataclass(frozen=True)
class ExampleConfig:
    """示例开关；每项能力的完整构造配置在 build_capabilities 中."""

    profile: Literal['learning', 'context', 'coder'] = 'learning'
    compaction: Literal['sliding', 'clear'] = 'sliding'
    model_name: str = field(default_factory=lambda: os.getenv('OLLAMA_MODEL', 'qwen2.5-harness:14b-16k'))
    base_url: str = field(default_factory=lambda: os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1'))
    temperature: float = 0.2
    max_tokens: int = 1024
    request_limit: int = 16
    tool_calls_limit: int = 24
    workspace: Path = field(default_factory=lambda: Path('.cache/harness-example/workspace'))

    def __post_init__(self) -> None:
        if self.request_limit < 1 or self.tool_calls_limit < 1:
            raise ValueError('模型请求和工具调用预算必须为正整数。')


def build_capabilities(config: ExampleConfig) -> list[AbstractCapability[LearningDeps]]:
    """把可独立使用的能力组合起来；构造参数刻意展开，便于断点观察和修改."""
    capabilities: list[AbstractCapability[LearningDeps]] = [
        LearningFlow(),
        AskUser[LearningDeps](
            answerer=None,  # 交还给应用处理，不在工具中读取终端。
            timeout=None,  # answerer=None 时不能设置等待超时。
            id='ask_user',
            description=None,
            defer_loading=False,
        ),
    ]
    if config.profile == 'learning':
        return capabilities

    if config.profile == 'coder':
        if os.name == 'nt':
            raise RuntimeError(
                'Coder 的 LocalWorkspace 需要 POSIX；请用 VS Code Remote - WSL 打开仓库运行 coder 组合。'
            )
        config.workspace.mkdir(parents=True, exist_ok=True)
        capabilities.extend(
            [
                LocalWorkspace[LearningDeps](
                    config.workspace,
                    read_only=False,
                    env=None,
                    id='local_workspace',
                    description=None,
                    defer_loading=False,
                ),
                Coder[LearningDeps](
                    workspace=None,  # 兼容旧接口，已被忽略；目录由上面的 LocalWorkspace 提供。
                    instructions='这是学习用工作区。用中文解释操作，只在用户要求时修改文件或执行命令。',
                    unrestricted_filesystem=False,
                    repo_context=True,
                    sub_agents=False,  # 改为 True 可观察 delegate_task；会增加本地模型请求。
                    agent_folders=None,
                ),
            ]
        )
        # Coder 自带压缩、结果限制和子代理配置，不再叠加 context 组合。
        return capabilities

    # 显式 store 在同一个 Agent 的暂停/恢复之间共享；本例退出后不保存。
    capabilities.extend(
        [
            Planning[LearningDeps](
                guidance='多步骤任务可用 write_plan 列出计划，用 read_plan 查看；完成后更新状态。',
                cache_ttl='5m',
                store=InMemoryPlanStore(),
                store_resolver=None,
                enable_subtasks=False,
                inject=True,
                tools=['write_plan', 'read_plan'],
                descriptions=None,
                id='planning',
                description=None,
                defer_loading=False,
            ),
            Memory[LearningDeps](
                store=InMemoryStore(),
                store_resolver=None,
                agent_name='harness_learning',
                namespace='local_demo',
                inject_memory=True,
                max_tokens=2000,
                max_lines=200,
                max_memory_size=65536,
                max_search_results=10,
                max_search_result_chars=4000,
                max_search_files=1000,
                guidance=None,
                injection_errors='raise',
                heading='学习笔记',
                id='memory',
                description=None,
                defer_loading=False,
            ),
            StepPersistence[LearningDeps](
                store=InMemoryStepStore(max_snapshots_per_run=30),
                agent_name='harness_learning',
                run_id=None,
                parent_run_id=None,
                metadata={'example': 'ollama'},
                capture_frontier=False,
                id='step_persistence',
                description=None,
                defer_loading=False,
            ),
            SystemReminders[LearningDeps](
                reminders=[
                    Reminder[LearningDeps](
                        content='先查询概念，再调用 ask_user_question；收到用户回答后直接解释，不重复追问。',
                        interval=3,
                        first_after=None,
                        trigger=None,
                        max_fires=3,
                        tag='system-reminder',
                    )
                ],
                dynamic_reminders=(),
                cache_ttl='5m',
                on_fire=None,
                id='system_reminders',
                description=None,
                defer_loading=False,
            ),
            WarnNearLimits[LearningDeps](
                max_iterations=config.request_limit,
                max_context_tokens=None,
                max_total_tokens=None,
                warn_on=['iterations'],
                warning_threshold=0.75,
                critical_remaining_iterations=2,
                max_context_fraction=None,
                context_window=None,
                fallback_context_window=200000,
                id='warn_near_limits',
                description=None,
                defer_loading=False,
            ),
        ]
    )
    # 以消息数量触发，避免把模型声明的最大窗口误认为 Ollama 实际 num_ctx。
    if config.compaction == 'sliding':
        capabilities.append(
            SlidingWindowCompaction[LearningDeps](
                max_messages=24,
                max_tokens=None,
                keep_messages=16,
                keep_tokens=None,
                tokenizer=None,
                preserve_first_user_message=True,
                receipts=False,
                max_fraction=None,
                context_window=None,
                fallback_context_window=200000,
                id='sliding_window',
                description=None,
                defer_loading=False,
            )
        )
    else:
        capabilities.append(
            ClearToolResults[LearningDeps](
                max_messages=24,
                max_tokens=None,
                keep_pairs=4,
                placeholder='[旧工具结果已清理]',
                exclude_tools=frozenset({TOOL_NAME, 'explain_concept'}),
                clear_tool_inputs=False,
                min_clear_tokens=None,
                tokenizer=None,
                max_fraction=None,
                context_window=None,
                fallback_context_window=200000,
                id='clear_tool_results',
                description=None,
                defer_loading=False,
            )
        )
    return capabilities


def build_agent(config: ExampleConfig) -> Agent[LearningDeps, str | DeferredToolRequests]:
    """沿用 main.py 的 Ollama 设置，把手写追问工具换成 Harness AskUser."""
    model = OpenAIChatModel(config.model_name, provider=OllamaProvider(base_url=config.base_url))
    agent = Agent(
        model,
        name='harness_learning',
        deps_type=LearningDeps,
        output_type=[str, DeferredToolRequests],
        instructions=(
            '你是中文 Pydantic AI Harness 学习助手。'
            '先调用 explain_concept 查询概念。'
            '如果历史中没有 ask_user_question 的工具返回结果，必须调用 ask_user_question 追问用户，'
            '只问用户偏好的解释角度，例如业务例子或内部顺序；不要要求用户解释源码或回答知识测验。'
            '只提出一个问题，提供 2 个中文选项，multi_select=false。'
            '收到该工具返回结果后，结合原问题和用户回答给出简短解释和例子，不要再次追问。'
            '不要编造用户回答。普通工具由模型选择调用，capability 钩子由框架调用。'
            'ask_user_result 是应用调用的 Python 辅助函数，不是模型工具。'
            'Planning 和 Memory 是可选辅助；只有需要时才调用它们的工具。'
        ),
        capabilities=build_capabilities(config),
        model_settings={'temperature': config.temperature, 'max_tokens': config.max_tokens},
        retries=4,
    )

    def explain_concept(
        ctx: RunContext[LearningDeps], concept: Literal['Agent', 'capability', '组合', '暂停恢复']
    ) -> str:
        """查询 Harness 的核心概念，演示普通 Python 工具与内置能力一起使用."""
        explanations = {
            'Agent': 'Agent 执行模型与工具循环；Harness 的能力通过 Agent(capabilities=[...]) 加入。',
            'capability': 'Capability 可以提供工具、指令和生命周期钩子；AskUser、Planning、Memory 是现成能力。',
            '组合': '把多个能力放入 capabilities 列表；Coder 自身也组合了文件、Shell、上下文管理等能力。',
            '暂停恢复': (
                'AskUser(answerer=None) 的工具调用抛出 CallDeferred，使 agent.run 返回 DeferredToolRequests。'
                '此时用户还没有回答；应用在暂停后收集回答，再用 ask_user_result 校验回答，'
                '通过 requests.build_results 和 conversation 在新的 run 中恢复。'
            ),
        }
        print(f'[tool] explain_concept({concept!r})')
        ctx.deps.concept_explained = True
        return explanations[concept]

    def validate_answer(
        ctx: RunContext[LearningDeps], output: str | DeferredToolRequests
    ) -> str | DeferredToolRequests:
        if isinstance(output, str):
            if not ctx.deps.concept_explained:
                raise ModelRetry('请先调用 explain_concept 查询概念。')
            if not ctx.deps.answers_received:
                raise ModelRetry('请调用 ask_user_question 取得用户回答后再输出最终答案。')
        return output

    agent.tool(explain_concept)
    agent.output_validator(validate_answer)
    return agent


async def run_interactive(
    agent: Agent[LearningDeps, str | DeferredToolRequests],
    deps: LearningDeps,
    config: ExampleConfig,
    *,
    question: str | None = None,
    answer: str | None = None,
) -> AgentRunResult[str | DeferredToolRequests]:
    """展示原问题、结构化追问、宿主收集回答、恢复运行的完整过程."""
    question = question or read_answer('你想了解 Harness 的什么？\n你：')
    limits = UsageLimits(request_limit=config.request_limit, tool_calls_limit=config.tool_calls_limit)
    # 断点 1：展开 agent 的 capabilities，观察模型看到哪些工具。
    result = await agent.run(question, deps=deps, usage_limits=limits)

    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        if requests.approvals or not requests.calls:
            raise RuntimeError('本例只处理 AskUser 的延迟调用，不处理审批请求。')
        calls: dict[str, dict[str, list[str]] | str] = {}
        for call in requests.calls:
            if call.tool_name != TOOL_NAME:
                raise RuntimeError(f'本例未注册 {call.tool_name!r} 的外部处理程序。')
            # 断点 2：用公开 API 解析请求，兼容 JSON 字符串和字典参数。
            request = AskUserRequest.from_tool_call(call)
            answers: list[AskUserAnswer] = []
            for item in request.questions:
                print(f'\nLLM 追问 [{item.header}]：{item.question}')
                for option in item.options:
                    print(f'  - {option.label}' + (f'：{option.description}' if option.description else ''))
                text = answer or read_answer('输入选项文字或你自己的回答：')
                answers.append(AskUserAnswer(header=item.header, custom_answer=text))
            response = AskUserResponse(answers=tuple(answers), cancelled=False)
            # 断点 3：验证回答并按 tool_call_id 填回工具结果。
            calls[call.tool_call_id] = ask_user_result(request, response)
            deps.answers_received += len(answers)

        deferred_results = requests.build_results(calls=calls)
        print('[应用] 已收集回答，携带同一 conversation 恢复运行。')
        result = await agent.run(
            conversation=result.conversation,
            deps=deps,
            deferred_tool_results=deferred_results,
            usage_limits=limits,
        )

    print(f'\n最终答案：\n{result.output}')
    print(f'\n累计请求：{result.usage.requests}；成功工具调用：{result.usage.tool_calls}')
    return result


async def main() -> None:
    """命令行与 VS Code 使用同一个入口和配置."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['learning', 'context', 'coder'], default='learning')
    parser.add_argument('--compaction', choices=['sliding', 'clear'], default='sliding')
    parser.add_argument('--workspace', type=Path, default=Path('.cache/harness-example/workspace'))
    parser.add_argument('--question', help='预填原问题；省略时从终端读取')
    parser.add_argument('--answer', help='为每个追问提供同一条自定义回答；省略时逐个从终端读取')
    args = parser.parse_args()
    config = ExampleConfig(profile=args.profile, compaction=args.compaction, workspace=args.workspace)
    print(f'[配置] profile={config.profile}；model={config.model_name}；base_url={config.base_url}')
    async with build_agent(config) as agent:
        await run_interactive(agent, LearningDeps(), config, question=args.question, answer=args.answer)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print('\n已退出交互。')
