"""中文 Harness 综合学习示例；配置全部写死，先读 build_agent，再读 main."""  # 直接运行，无需参数或输入。

import asyncio  # 标准库：驱动 Agent、工具和存储所使用的异步接口。
import json  # 标准库：保存实际给模型看的工具定义，便于学习 JSON Schema。
from dataclasses import dataclass, field, replace  # 依赖容器，以及不修改原始工具定义的复制操作。
from os import getenv, name as platform_name  # 判断当前 Python 所在平台，提前解释本地工作区限制。
from pathlib import Path  # 所有示例输出都按脚本位置定位，不依赖终端当前目录。

from tool_descriptions import TOOL_DESCRIPTIONS  # 本目录的中文工具说明，逐个说明用途和参数。

from pydantic_ai import Agent, ModelRetry, RunContext  # 核心执行器、可恢复工具错误和依赖上下文。
from pydantic_ai.capabilities import LocalWorkspace, PrepareTools  # 核心能力：工作区，以及发送前修改工具定义。
from pydantic_ai.models.openai import OpenAIChatModel  # 使用 Ollama 的 OpenAI 兼容接口。
from pydantic_ai.providers.ollama import OllamaProvider  # 本地 Ollama 不需要 API 密钥。
from pydantic_ai.tools import ToolDefinition  # 核心工具定义包含名称、描述和参数 JSON Schema。
from pydantic_ai.usage import UsageLimits  # 核心硬预算：超过请求上限时终止运行。
from pydantic_ai_harness import (  # Harness 能力按需导入；不要用星号导入全部可选集成。
    AskUser,  # 在模型执行途中向人提出结构化问题。
    ClampOversizedMessages,  # 限制历史中单个文本片段的大小。
    ClearToolResults,  # 清理较旧的工具返回，减小后续请求的上下文负担。
    ConversationSearch,  # 从已持久化的对话中检索细节，弥补压缩后的信息缺口。
    FileSystem,  # 将工作区读写能力变成模型可调用的工具。
    GuardrailResult,  # 护栏返回的放行、拒绝或重试决定。
    InputGuardrail,  # 在输入到达模型之前执行应用校验。
    Memory,  # 给 Agent 提供跨运行的笔记本。
    OutputGuardrail,  # 校验最终结果，不合格时可要求模型重新回答。
    Planning,  # 提供计划工具，并在请求尾部展示当前计划。
    RepoContext,  # 自动加载学习工作区中的 AGENTS.md 说明。
    ReportContextUsage,  # 发出上下文占用事件，便于 UI 或日志展示。
    Shell,  # 在工作区执行命令；本例仅开放 echo。
    Skills,  # 发现技能目录，并按需加载 SKILL.md 指引。
    SlidingWindowCompaction,  # 请求过长时仅向模型发送较近的消息窗口。
    StepPersistence,  # 保存运行事件、消息快照和工具副作用记录。
    SubAgent,  # 子代理配置，包含名称、Agent 和调用预算。
    SubAgents,  # 将子代理配置转换为 delegate_task 工具。
    SystemReminders,  # 在若干次模型请求后重新提醒目标。
    ToolGuardrail,  # 在工具真正执行之前校验其调用参数。
    ToolOutputLimits,  # 在长工具结果进入消息历史时限制其长度。
    WarnNearLimits,  # 接近预算时提醒模型收尾；提醒本身不是硬限制。
)  # 核心 Agent 与 Harness 能力分属两个包，但共享同一运行上下文。
from pydantic_ai_harness.ask_user import AskUserAnswer, AskUserRequest, AskUserResponse  # 人机交互的类型化协议。
from pydantic_ai_harness.compaction import ContextUsageEvent  # 订阅占用事件，而不是使用已弃用的回调参数。
from pydantic_ai_harness.conversation_search import SnapshotHistorySource  # 把快照存储适配成对话搜索数据源。
from pydantic_ai_harness.guardrails import ToolCallInfo  # 工具护栏收到的名称和已校验参数。
from pydantic_ai_harness.memory import FileStore  # 记忆以 Markdown 文件形式保存在工作区。
from pydantic_ai_harness.planning import SqlitePlanStore  # 计划单独保存在本机 SQLite 中。
from pydantic_ai_harness.step_persistence import FileStepStore, continue_run  # 文件快照和恢复消息历史的辅助函数。
from pydantic_ai_harness.system_reminders import Reminder  # 配置提醒内容和发送间隔。
from pydantic_ai_harness.tool_output_limits import Band, Truncate  # 按结果长度选择截断策略。

OLLAMA_MODEL = getenv('OLLAMA_MODEL', 'qwen2.5:14b-instruct-q4_K_M')  # 默认使用本机已安装的工具调用模型。
OLLAMA_BASE_URL = getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')  # WSL 可通过环境变量指定 Windows 地址。

WORKSPACE = Path(__file__).resolve().parent / 'output' / 'demo'  # 固定学习目录；重复运行复用计划、记忆和快照。


@dataclass  # 普通应用数据，由 Pydantic AI 的 deps 注入，不需要模型生成。
class LearningDeps:  # 每次运行使用独立依赖对象，避免并发用户之间混用状态。
    """学习者身份和工具目录；工具通过 ctx.deps 获取，身份不会变成工具参数."""  # 依赖注入的作用。

    learner: str = '中文学习者'  # 应用确定的身份，实际项目应来自认证系统。
    tools: dict[str, ToolDefinition] = field(  # 收集本轮工具定义。
        default_factory=dict[str, ToolDefinition]  # 每次创建独立字典。
    )  # 收集实际注册的工具，运行后导出供学习。


async def chinese_tools(  # 在每次模型请求前准备工具定义。
    ctx: RunContext[LearningDeps],  # 接收运行依赖。
    tools: list[ToolDefinition],  # 上下文提供依赖，tools 是本次请求可用工具。
) -> list[ToolDefinition]:  # 核心准备钩子。
    """给当前启用的工具设置中文说明，保留原参数约束和内置工具行为."""  # 工具返回值仍遵循上游协议。
    translated = [replace(tool, description=TOOL_DESCRIPTIONS[tool.name]) for tool in tools]  # 漏翻译的工具会立即报错。
    ctx.deps.tools.update({tool.name: tool for tool in translated})  # 保存副本，用于学习实际模型请求中的工具定义。
    return translated  # 返回给核心；核心再将它们转换成各模型供应商需要的格式。


def input_guard(prompt: str) -> GuardrailResult:  # 本地规则无需额外模型请求。
    """拒绝含演示禁用标记的输入；这是业务规则示范，不是通用安全检测器."""  # 不声称检测所有提示注入。
    if '示例禁止' in prompt:  # 一个容易手工验证的教学条件。
        return GuardrailResult.block('输入包含本例的禁用标记。')  # 核心不会继续发送这个输入到模型。
    return GuardrailResult.allow()  # 普通学习请求进入正常 Agent 循环。


def output_guard(output: object) -> GuardrailResult:  # 输出也可以是 Pydantic 模型，所以接口接收 object。
    """要求最终答案包含总结，演示 Harness 如何复用核心的输出重试机制."""  # 本例输出类型是 str。
    if not isinstance(output, str) or '总结' not in output:  # 先用类型收窄，再检查文本。
        return GuardrailResult.retry('请用中文回答，并包含“总结”二字。')  # 计入核心 Agent 的输出重试预算。
    return GuardrailResult.allow()  # 合格结果交回应用。


def tool_guard(call: ToolCallInfo) -> GuardrailResult:  # 工具执行前可读取校验过的参数。
    """示范应用如何限制写入目标和删除记忆，FileSystem 仍负责自己的路径检查."""  # 不代替工作区隔离。
    if call.name == 'delete_memory' or (  # 本例不允许模型删除长期记忆。
        call.name == 'write_file' and call.args.get('path') != 'report.md'  # 文件写入只允许这个教学目标。
    ):  # 教学限制。
        return GuardrailResult.block('本例只允许写 report.md，并保留所有学习记忆。')  # 跳过操作，将拒绝原因返回模型。
    return GuardrailResult.allow()  # 允许的操作交回原工具执行。


def build_agent() -> tuple[Agent[LearningDeps, str], FileStepStore]:  # 无需传参，所有示例配置直接写在函数中。
    """用固定模型、固定工作区和固定回答组装学习助手."""  # 阅读重点是 capabilities 列表。
    store = FileStepStore(WORKSPACE / 'steps')  # 快照存储使用宿主机路径，不随 workspace 后端自动迁移。
    model = OpenAIChatModel(  # 主代理和子代理都通过本地 Ollama 推理。
        OLLAMA_MODEL,
        provider=OllamaProvider(base_url=OLLAMA_BASE_URL),  # 使用同一个模型，避免加载两份权重。
    )  # 工具调用仍由 Agent 校验和执行。
    reviewer = Agent(  # 子代理是另一个普通核心 Agent，有自己的消息历史。
        model,  # 子代理也使用真实本地模型审阅。
        name='reviewer',  # 主代理用此名称选择委派对象。
        instructions='用中文检查任务中的概念是否正确，只返回简短意见。',  # 子代理只负责概念审阅。
    )  # 子代理未获得文件或 Shell 工具，所以这里只能返回文字意见。

    async def answer_user(request: AskUserRequest) -> AskUserResponse:  # AskUser 将校验过的问题交给应用。
        """固定选择每个问题的第一项，演示提问协议，不等待终端输入."""  # 模拟回答不代表真实用户批准。
        answers: list[AskUserAnswer] = []  # 为每个问题生成一个强类型回答。
        for question in request.questions:  # 支持工具一次提出多个问题。
            print(f'[模拟回答] {question.header}：{question.options[0].label}')  # 明确显示预设选择。
            answers.append(  # 保存当前问题的固定模拟答案。
                AskUserAnswer(header=question.header, selected=(question.options[0].label,))  # 首选项对应问题标题。
            )  # 答案由示例代码预设。
        return AskUserResponse(answers=tuple(answers))  # 回答按 header 与问题匹配。

    agent = Agent(  # 真正的运行入口仍然是 pydantic_ai.Agent。
        model,  # 本地模型自主选择工具，不再按固定剧本响应。
        deps_type=LearningDeps,  # 明确工具可访问的依赖类型。
        instructions='用中文学习 Harness：读取 lesson.txt，加载 study-notes 技能，制定计划并执行。最终给出总结。',  # 主目标。
        capabilities=[  # 组合二十个 Harness 能力，以及两个核心能力。
            LocalWorkspace(WORKSPACE),  # 核心：统一文件与命令的工作目录；本地目录不是安全沙箱。
            InputGuardrail(guard=input_guard),  # Harness：进入模型前检查输入。
            StepPersistence(store=store),  # Harness：每个已稳定步骤保存快照，可找回压缩前的信息。
            ClampOversizedMessages(max_part_chars=12_000),  # Harness：对过大的单个历史文本片段作兜底。
            ClearToolResults(  # 清理历史中的旧工具结果，不重跑原工具。
                max_messages=12,  # 超过十二条消息才清理。
                keep_pairs=3,  # 保留最近三组交互。
                placeholder='[旧工具结果已清理，可搜索历史]',  # 保留最近三组工具交互。
            ),  # Harness：清旧结果。
            SlidingWindowCompaction(max_messages=24, keep_messages=16),  # Harness：过长请求保留最近窗口和首个用户消息。
            Memory(FileStore('memory'), max_tokens=600),  # Harness：在压缩之后注入长期记忆，避免刚注入就被移除。
            FileSystem(  # 将工作区文件访问注册为工具。
                tools=['read_file', 'write_file', 'list_directory'],  # 仅开放三种文件操作。
                content_hashes=False,  # 单写者示例省略并发内容哈希。
            ),  # Harness：本例单写者文件工具。
            Shell(  # 只学习同步完成的一次命令，不引入后台进程管理。
                tools=['run_command'],  # 只注册一次性命令工具。
                allowed_commands=['echo'],  # 仅允许演示用的 echo。
                denied_operators=['>', '>>', '|', ';', '&&'],  # 缩小演示范围。
            ),  # 命令演示。
            RepoContext(),  # Harness：读取当前学习目录的 AGENTS.md，不扫描整个源码仓库。
            Skills('skills'),  # Harness：只发现指定目录中的技能，按需加载正文。
            Planning(  # 计划存储独立于消息快照，恢复对话不会自动恢复所有能力状态。
                store=SqlitePlanStore(str(WORKSPACE / 'plan.db')),  # 本机 SQLite 保存计划。
                tools=['write_plan', 'read_plan'],  # 使用整表读写方便理解。
            ),  # Harness：持久计划。
            SystemReminders(  # 提醒只影响当前模型请求，不不断累积在消息历史中。
                reminders=[Reminder('保持中文解释，完成后更新计划并给出总结。', interval=4)]  # 每四次请求提醒一次。
            ),  # 周期性提醒。
            AskUser(answerer=answer_user),  # Harness：提问协议与终端界面解耦。
            SubAgents(  # 把独立 Agent 暴露给父代理委派。
                agents=[SubAgent(reviewer, description='检查学习总结的概念', max_calls=2)],  # 配置子代理与调用次数。
                max_depth=2,  # 限制次数和深度。
            ),  # 有限委派。
            ConversationSearch(SnapshotHistorySource(store), scope='conversation'),  # Harness：只查当前对话的历史。
            ToolGuardrail(guard=tool_guard),  # Harness：执行前约束文件目标和记忆删除。
            ToolOutputLimits(  # 新结果进入历史之前限长，与历史压缩的时机不同。
                per_tool={  # 按工具指定输出策略。
                    'long_reference': [Band(over=500, action=Truncate(max_chars=350))]  # 超过阈值后截短长资料。
                }  # 长参考资料保留有限字符。
            ),  # 截短长返回。
            WarnNearLimits(max_iterations=20, warning_threshold=0.7),  # Harness：接近轮数预算时提醒收尾。
            ReportContextUsage(context_window=32_000),  # Harness：教学指定窗口并发事件；不是供应商上下文窗口声明。
            OutputGuardrail(guard=output_guard),  # Harness：最终输出必须通过业务校验。
            PrepareTools(chinese_tools),  # 核心：把上面所有工具的模型可见描述替换成中文。
        ],  # 能力在钩子、工具与指令层组合，不是二十个独立执行循环。
    )  # 构造完成后再注册两个自己的业务工具。

    def learning_progress(ctx: RunContext[LearningDeps], completed: int, total: int) -> str:  # 模型只传后两个参数。
        """计算学习进度；completed 为已完成数，total 为总数，ctx 提供应用注入的学习者身份."""  # 中文工具正文说明。
        if total <= 0 or not 0 <= completed <= total:  # 业务约束不只依赖 int 类型校验。
            raise ModelRetry('请满足 total > 0 且 0 <= completed <= total。')  # 核心将错误发给模型请求纠正参数。
        return f'{ctx.deps.learner}：已完成 {completed}/{total}，进度 {completed / total:.0%}。'  # 实际工具计算结果。

    def long_reference() -> str:  # 生成大结果，刻意触发 ToolOutputLimits。
        """返回长篇中文参考资料，供学习者观察工具输出限长与历史清理的不同作用时机."""  # 中文工具说明。
        return 'Agent 管理执行循环；Harness 能力组合工具、指令和生命周期钩子。\n' * 100  # 原始结果远大于截断阈值。

    async def show_context(ctx: RunContext[LearningDeps], event: ContextUsageEvent) -> None:  # 用强类型字段观察运行。
        """将每次模型请求的估算上下文大小打印出来；不是供应商实际计费 token."""  # 可改接应用 UI。
        print(f'[上下文] {ctx.deps.learner}：估算 {event.used_tokens}/{event.window_tokens} token')  # 可视化运行过程。

    agent.tool(learning_progress)  # 注册需要 RunContext 的工具，等价于在函数上写 @agent.tool。
    agent.tool_plain(long_reference)  # 注册不需要上下文的普通工具，等价于 @agent.tool_plain。
    agent.on_event(ContextUsageEvent)(show_context)  # 注册事件监听函数，事件由 ReportContextUsage 发出。
    return agent, store  # 应用仍可直接访问存储，实现继续会话或读取运行记录。


async def main() -> None:  # 应用层负责目录、依赖、Agent 生命周期与结果展示。
    """使用固定学习工作区，跑完流程，并保存可检查的消息历史与工具定义."""  # 不更改框架源码。
    if platform_name != 'posix':  # 当前源码的本地工作区要求 POSIX 的进程组与超时语义。
        raise SystemExit('综合示例请用 WSL/Linux/macOS 运行，详见 README.md。')  # 固定中文提示，不引入命令行解析器。
    skill_dir = WORKSPACE / 'skills' / 'study-notes'  # Skills 扫描库下每个子目录中的 SKILL.md。
    skill_dir.mkdir(parents=True, exist_ok=True)  # 同时创建本次演示的工作区。
    (WORKSPACE / 'lesson.txt').write_text(  # 为文件工具准备真实输入。
        'Agent 管执行循环。Harness 提供计划、工具、记忆和钩子。\n',  # 初始化中文学习资料。
        encoding='utf-8',  # 本次练习的中文资料。
    )  # 资料。
    (WORKSPACE / 'AGENTS.md').write_text(  # RepoContext 会自动读取当前工作区的此文件。
        '请用中文回答。只把学习报告写入 report.md。\n',  # 初始化项目说明。
        encoding='utf-8',  # 指令配合工具护栏，但文字本身不等于权限控制。
    )  # 仓库上下文。
    (skill_dir / 'SKILL.md').write_text(  # 这是演示 Agent 的技能资料，不是修改当前编码助手的技能。
        '---\nname: study-notes\ndescription: 用中文整理 Harness 学习笔记。\n---\n'  # 标准技能目录的元数据。
        '读取 lesson.txt；区分核心与 Harness；检查概念后写报告、保存记忆并完成计划。\n',  # 模型按需读取的技能正文。
        encoding='utf-8',  # 在 Windows 上也保持中文编码一致。
    )  # 技能文件写入完成。
    print(f'本地模型：{OLLAMA_MODEL}；接口：{OLLAMA_BASE_URL}')  # 便于确认连接的 Ollama 实例。
    agent, store = build_agent()  # 直接构造固定配置的示例，不传入模型、目录或模式开关。
    deps = LearningDeps()  # 每次运行独立的依赖对象。
    async with agent:  # 管理工具集、工作区等需要释放的异步资源。
        result = await agent.run(  # 核心循环：请求模型、执行工具、发回结果，直到得到最终回答。
            '学习 Harness，使用可用工具完成资料阅读、计划、提问、审阅、记忆和 report.md，并给出总结。',  # 任务输入。
            deps=deps,  # 用户身份来自应用，工具通过 ctx.deps 使用。
            usage_limits=UsageLimits(request_limit=30, tool_calls_limit=30),  # 真正限制请求与工具调用，防止无限循环。
        )  # 本地模型自主执行；提问仍使用模拟回答。
    (WORKSPACE / 'messages.json').write_bytes(result.all_messages_json())  # 保存核心消息格式，观察工具调用与返回。
    definitions = {  # 导出实际提供给模型的工具目录。
        name: {'说明': tool.description, '参数模式': tool.parameters_json_schema}  # 每个工具的中文说明和参数。
        for name, tool in deps.tools.items()  # 保留模式约束。
    }  # 目录。
    (WORKSPACE / 'tools.json').write_text(  # 以可阅读的形式保存工具说明和参数模式。
        json.dumps(definitions, ensure_ascii=False, indent=2),  # 把目录转换成易读 JSON。
        encoding='utf-8',  # 保留中文字符，不转成 Unicode 转义。
    )  # 中文工具索引。
    runs = await store.list_runs(conversation_id=result.conversation_id)  # 查询当前对话对应的运行记录。
    history = await continue_run(store, run_id=runs[-1].run_id)  # 恢复最近的完整消息快照；这里不额外请求模型。
    print(f'\n{result.output}')  # 经过 OutputGuardrail 校验的最终答案。
    print(  # 展示持久化与核心用量统计的结果。
        f'已保存快照，可恢复 {len(history)} 条消息；请求数：{result.usage.requests}。'  # 恢复出来的是消息，不是完整进程。
    )  # 包含计入父运行的子代理用量。
    print(f'产物目录：{WORKSPACE}')  # 可直接打开报告、消息、工具说明、计划数据库和长期记忆。


if __name__ == '__main__':  # 导入函数时不执行示例。
    asyncio.run(main())  # 在一个事件循环中完成所有异步工作。
