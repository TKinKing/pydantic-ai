# Harness 完整参数索引

运行和 VS Code 调试入口见 [README.md](README.md)。当前仓库的 Harness 是能力库，没有统一的 `Harness(...)` 构造器。把能力实例传给 `Agent(capabilities=[...])`，模型则配置在 Agent 或对应子代理中。

本页覆盖 `pydantic_ai_harness` 顶层导出的 **57 个能力构造器**，以及 `SubAgent`、`GuardrailResult` 和工作区辅助对象。参数名、类型和默认值来自本次工作区的本地源码与 `inspect.signature`；未安装的可选依赖使用 AST 核对，并在对应项标明。它是当前检出版本的参数快照；升级后以安装版本的签名和能力文档为准。嵌套配置对象、第三方 SDK 参数及各子模块另外导出的类型请进入相应能力文档。

“完整参数”表示可以查到每个构造参数，不表示所有能力同时启用，也不表示全部参数取值的笛卡尔积都能运行。大段默认提示词保留源码常量名；`factory:` 表示每个实例分别创建默认对象；“必填”表示构造时必须提供。表格按参数名查询，调用时建议使用关键字参数。

## 如何选择组合

| 目标 | 组合方式 |
| --- | --- |
| 本地文件和编码 | 一个 `LocalWorkspace(...)` 加 `Coder(...)` |
| 逐项理解能力 | 一个 workspace 加显式 `FileSystem`、`Shell`、`Planning` 等能力 |
| 本地模型研究任务 | 一个 workspace 加 `Researcher(...)`；搜索和抓取需要网络 |
| 主模型与辅助模型分开 | Agent 配置主模型，`SubAgent` 的 Agent、`Advisor`、摘要/评审能力配置辅助模型 |
| 可重复的离线流程检查 | `test_main.py` 的 `FunctionModel` 流程测试；不用于证明真实模型的工具调用质量 |

`LocalWorkspace` 属于 Pydantic AI core。Agent 的 `model`、`model_settings`、`deps_type`、`output_type`，以及运行时的 `usage_limits`、`message_history` 等也属于 core，不是 Harness 构造参数，见 [Agent 文档](../docs/agent.md)。本地 OpenAI 兼容服务应共享显式配置了 `base_url` 的模型对象，避免辅助能力退回默认云端 provider。

`Coder`、`Researcher` 已组合若干能力。重复添加相同工具名、冲突的同 ID 能力或多个 workspace 提供者前，先阅读对应能力的合并规则。需要云服务凭据、浏览器、容器或可选 SDK 的能力在本地模型之外还有自己的运行前提。

## 通用能力参数

部分能力继承以下三个参数。本页在每个支持它们的构造器旁明确列出实际默认值；没有该行的构造器不接收这组参数。

| 参数 | 类型 | 用途 |
| --- | --- | --- |
| `id` | `str \| None` | 标识能力实例；部分工具和持久化流程使用它作为身份。 |
| `description` | `str \| None` | 能力描述；按能力加载方式提供给使用方。 |
| `defer_loading` | `bool` | 是否延迟加载；workspace 提供能力等有自己的限制，见各自文档。 |

## 组合入口

### `Coder`

[能力文档](../docs/harness/coder.md)。

`workspace` 是已弃用且被忽略的兼容参数。实际目录由并列的 `LocalWorkspace(path)` 或沙箱能力提供。`instructions` 追加到内置说明；`sub_agents=True` 会委派给当前 Agent，须在 `Agent(capabilities=...)` 构建时绑定。已包含文件、Shell、RepoContext、SubAgents、清理和输出限制，额外组合前先检查重复工具与能力配置。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `workspace` | `str \| Path \| None` | `None` |
| `instructions` | `str \| None` | `None` |
| `unrestricted_filesystem` | `bool` | `False` |
| `repo_context` | `bool` | `True` |
| `sub_agents` | `bool` | `True` |
| `agent_folders` | `str \| Sequence[str \| Path] \| None` | `None` |

### `Researcher`

[能力文档](../docs/harness/researcher.md)。

`instructions` 替换内置说明，`None` 不加入默认说明。`subagents=None` 创建默认 researcher；`subagents=[]` 禁用委派。优先使用模型原生搜索/抓取；原生能力不可用时使用 `local=True` 开启的本地回退。搜索与抓取仍访问互联网。默认输出溢出存储依赖 workspace；传非 workspace 的 `store` 可取消这一要求。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `instructions` | `str \| None` | `DEFAULT_RESEARCHER_INSTRUCTIONS` |
| `subagents` | `Sequence[SubAgent[AgentDepsT]] \| None` | `None` |
| `store` | `OverflowStore \| WorkspaceStore \| None` | `None` |

## 文件、命令与上下文

### `FileSystem`

[能力文档](../docs/harness/filesystem.md)。

`cwd` 是已弃用且被忽略的兼容参数，实际目录由 workspace 提供。`protected_patterns` 已弃用，请使用 `read_only_patterns`。目录、允许/拒绝模式与只读模式的关系见能力文档。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `root_dir` | `str \| Path \| None` | `None` |
| `cwd` | `str \| Path \| None` | `None` |
| `allowed_patterns` | `Sequence[str]` | `factory: list[str]` |
| `denied_patterns` | `Sequence[str]` | `factory: list[str]` |
| `read_only_patterns` | `Sequence[str]` | `('**/.git/*', '**/.env', '**/.env.*', '*.pem', '*.key', '**/secrets*', '**/.pydantic-ai-harness/**')` |
| `max_read_lines` | `int` | `2000` |
| `max_read_chars` | `int \| None` | `50000` |
| `max_list_results` | `int` | `1000` |
| `max_search_results` | `int` | `1000` |
| `max_find_results` | `int` | `1000` |
| `read_only` | `bool` | `False` |
| `content_hashes` | `bool` | `True` |
| `tools` | `Sequence[str]` | `('read_file', 'write_file', 'edit_file', 'list_directory', 'search_files', 'find_files', 'create_directory', 'file_info')` |
| `max_retries` | `int \| None` | `None` |
| `protected_patterns` | `Sequence[str] \| None` | `None` |

### `Shell`

[能力文档](../docs/harness/shell.md)。

`cwd` 是已弃用且被忽略的兼容参数，命令从 workspace 的工作目录执行。限制命令名称不等于操作系统沙箱；根据任务选择本地、只读或隔离 workspace。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `cwd` | `str \| Path \| None` | `None` |
| `allowed_commands` | `Sequence[str]` | `factory: list[str]` |
| `denied_commands` | `Sequence[str]` | `('rm', 'rmdir', 'mkfs', 'dd', 'format', 'shutdown', 'reboot', 'halt', 'poweroff', 'init')` |
| `denied_operators` | `Sequence[str]` | `factory: list[str]` |
| `default_timeout` | `float` | `30.0` |
| `max_output_chars` | `int` | `50000` |
| `persist_cwd` | `bool` | `False` |
| `allow_interactive` | `bool` | `False` |
| `env` | `Mapping[str, str] \| None` | `None` |
| `denied_env_patterns` | `Sequence[str]` | `factory: list[str]` |
| `tools` | `Sequence[str]` | `('run_command', 'start_command', 'check_command', 'stop_command')` |
| `max_file_bytes` | `int \| None` | `None` |

### `RepoContext`

[能力文档](../docs/harness/repo-context.md)。

`workspace_dir` 已弃用且被忽略，扫描基于运行时 workspace 的工作目录。`traversal_tool_names`、`traversal_path_arg` 也属于弃用兼容参数。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `workspace_dir` | `Path \| None` | `None` |
| `home_dir` | `str \| Path \| None` | `None` |
| `filenames` | `Sequence[str]` | `('CLAUDE.md', 'AGENTS.md')` |
| `autoload_instructions` | `bool` | `True` |
| `expose_inventory_tool` | `bool` | `False` |
| `inventory_tool_name` | `str` | `'inventory_agent_context'` |
| `nested_traversal` | `bool` | `False` |
| `nested_inject` | `Literal['pointer', 'contents']` | `'pointer'` |
| `traversal_tool_names` | `frozenset[str]` | `frozenset({'read_file', 'list_directory'})` |
| `traversal_path_arg` | `str` | `'path'` |
| `asset_roots` | `Sequence[str]` | `('.claude', '.agents', '.codex', '.grok')` |

### `Skills`

[能力文档](../docs/harness/skills.md)。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `directories` | `str \| Path \| Sequence[str \| Path]` | 必填 |
| `include` | `Collection[str] \| None` | `None` |
| `exclude` | `Collection[str] \| None` | `None` |
| `workspace` | `WorkspaceBackend \| None` | `None` |

### `PydanticAIDocs`

[能力文档](../docs/harness/pydantic-ai-docs.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `local_docs_path` | `Path \| None` | `None` |
| `cache` | `bool` | `True` |

## 协作、规划与委派

### `Planning`

[能力文档](../docs/harness/planning.md)。

通用参数默认值：`id='planning'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `guidance` | `str \| None` | `None` |
| `cache_ttl` | `Literal['5m', '1h']` | `'5m'` |
| `store` | `PlanStore \| None` | `None` |
| `store_resolver` | `Callable[[RunContext[AgentDepsT]], PlanStore] \| None` | `None` |
| `enable_subtasks` | `bool` | `False` |
| `inject` | `bool` | `True` |
| `tools` | `Sequence[str] \| None` | `None` |
| `descriptions` | `dict[str, str] \| None` | `None` |

### `AskUser`

[能力文档](../docs/harness/ask-user.md)。

`answerer` 是必填参数；可传回调，或传 `None` 使用延迟回答流程。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `answerer` | `Answerer \| None` | 必填 |
| `timeout` | `float \| None` | `None` |

### `SubAgents`

[能力文档](../docs/harness/subagents.md)。

`agents` 内的 Agent 可以分别绑定不同本地模型。`models` 提供模型别名映射；`shared_capabilities` 和 `inherit_tools` 会影响委派 Agent 能使用的能力。 `inherit_tools=True` 已弃用，新组合优先明确提供子代理能力。

通用参数默认值：`id='sub_agents'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `agents` | `Sequence[SubAgent[AgentDepsT]]` | `()` |
| `models` | `Mapping[str, Model \| KnownModelName \| str \| ModelOption]` | `factory: dict[str, 'Model \| KnownModelName \| str \| ModelOption']` |
| `agent_folders` | `str \| Sequence[str \| Path] \| None` | `None` |
| `agent_overrides` | `Mapping[str, AgentOverride]` | `factory: dict[str, AgentOverride]` |
| `tool_resolver` | `ToolResolver \| None` | `None` |
| `forward_usage` | `bool` | `True` |
| `inherit_tools` | `bool` | `False` |
| `shared_capabilities` | `Sequence[AgentCapability[AgentDepsT]]` | `()` |
| `event_stream_handler` | `EventStreamHandler[AgentDepsT] \| None` | `None` |
| `tool_name` | `str` | `'delegate_task'` |
| `tool_retries` | `int \| None` | `2` |
| `contain_errors` | `bool` | `False` |
| `include_self` | `bool` | `False` |
| `max_depth` | `int` | `3` |
| `workspace` | `WorkspaceBackend \| None` | `None` |

### `Advisor`

[能力文档](../docs/harness/advisor.md)。

本地模型组合明确传 `mode='local'` 和已配置 provider 的模型对象；`native` 路径依赖模型服务的原生能力。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `model` | `ModelSelection` | 必填 |
| `mode` | `Literal['auto', 'native', 'local']` | `'auto'` |
| `output_type` | `OutputSpec[object]` | `str` |
| `max_uses` | `int \| None` | `None` |
| `max_tokens` | `int \| None` | `None` |
| `caching` | `Literal['5m', '1h'] \| None` | `None` |
| `forward_history` | `bool` | `False` |

### `BackgroundTools`

[能力文档](../docs/harness/background-tools.md)。

通用参数默认值：`id='background_tools'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `tools` | `ToolSelector[AgentDepsT]` | `每实例新建 {'background': True}` |

### `SystemReminders`

[能力文档](../docs/harness/system-reminders.md)。

通用参数默认值：`id='system_reminders'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `reminders` | `Sequence[Reminder[AgentDepsT]]` | `()` |
| `dynamic_reminders` | `Sequence[DynamicReminder[AgentDepsT] \| AsyncDynamicReminder[AgentDepsT]]` | `()` |
| `cache_ttl` | `Literal['5m', '1h']` | `'5m'` |
| `on_fire` | `Callable[[str], None] \| None` | `None` |

## 记忆、持久化与预算

### `Memory`

[能力文档](../docs/harness/memory.md)。

默认 `InMemoryStore()` 仅在进程内保存。需要跨进程记忆时显式传持久化 store；`heading` 设置注入内容的 Markdown 标题，可区分多个记忆块。

通用参数默认值：`id='memory'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `store` | `MemoryStore` | `factory: InMemoryStore` |
| `store_resolver` | `Callable[[RunContext[AgentDepsT]], MemoryStore] \| None` | `None` |
| `agent_name` | `str` | `'main'` |
| `namespace` | `str \| Callable[[RunContext[AgentDepsT]], str]` | `''` |
| `inject_memory` | `bool` | `True` |
| `max_tokens` | `int` | `2000` |
| `max_lines` | `int` | `200` |
| `max_memory_size` | `int` | `65536` |
| `max_search_results` | `int` | `10` |
| `max_search_result_chars` | `int` | `4000` |
| `max_search_files` | `int` | `1000` |
| `guidance` | `str \| None` | `None` |
| `injection_errors` | `Literal['ignore', 'raise']` | `'ignore'` |
| `heading` | `str` | `''` |

### `StepPersistence`

[能力文档](../docs/harness/step-persistence.md)。

默认 `InMemoryStepStore()` 不持久化到磁盘。保存和恢复示例使用显式 store；`capture_frontier` 控制是否记录更细的执行位置。

通用参数默认值：`id='step_persistence'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `store` | `StepStore` | `factory: InMemoryStepStore` |
| `agent_name` | `str \| None` | `None` |
| `run_id` | `str \| None` | `None` |
| `parent_run_id` | `str \| None` | `None` |
| `metadata` | `dict[str, str]` | `每实例新建 {}` |
| `capture_frontier` | `bool` | `False` |

### `ConversationSearch`

[能力文档](../docs/harness/conversation-search.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `source` | `HistorySource` | 必填 |
| `scope` | `SearchScope \| None` | `None` |
| `tool_id` | `str` | `'conversation-search'` |
| `max_matches` | `int` | `10` |
| `context_lines` | `int` | `5` |
| `bm25_k1` | `float` | `1.5` |
| `bm25_b` | `float` | `0.75` |
| `add_instructions` | `bool` | `True` |

### `SpendLimits`

[能力文档](../docs/harness/spend.md)。

本地模型未必存在价格表。通过 `price` 定义计价，或按需求选择 `on_unpriced`；默认值 `zero` 会把无法计价的用量按零费用记录。

通用参数默认值：`id='spend_limits'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `budgets` | `Sequence[Budget[AgentDepsT]]` | `()` |
| `store` | `SpendStore \| BatchSpendStore` | `factory: InMemorySpendStore` |
| `price` | `PriceFunc \| None` | `None` |
| `on_spend` | `SpendCallback \| None` | `None` |
| `on_unpriced` | `Literal['zero', 'raise']` | `'zero'` |
| `expose_tools` | `bool` | `False` |
| `clock` | `Callable[[], datetime]` | `utc_now` |

### `AbsurdDurability`

[能力文档](../docs/harness/absurd.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `absurd`）。

需要 `absurd-sdk` 和 Absurd 服务上下文；它不是单独的本地文件检查点功能。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `models` | `Mapping[str, Model] \| None` | `None` |
| `event_stream_handler` | `EventStreamHandler[AgentDepsT] \| None` | `None` |
| `name` | `str \| None` | `None` |
| `parallel_execution_mode` | `AbsurdParallelExecutionMode` | `'sequential'` |

## 输入、输出与工具检查

### `InputGuardrail`

[能力文档](../docs/harness/guardrails.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `guard` | `InputGuardrailFunc[AgentDepsT] \| Sequence[InputGuardrailFunc[AgentDepsT]]` | 必填 |
| `parallel` | `bool` | `False` |

### `OutputGuardrail`

[能力文档](../docs/harness/guardrails.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `guard` | `OutputGuardrailFunc[AgentDepsT] \| Sequence[OutputGuardrailFunc[AgentDepsT]]` | 必填 |

### `ToolGuardrail`

[能力文档](../docs/harness/guardrails.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `guard` | `ToolGuardrailFunc[AgentDepsT] \| None` | `None` |
| `result_guard` | `ToolResultGuardrailFunc[AgentDepsT] \| None` | `None` |
| `tools` | `Sequence[str] \| None` | `None` |
| `hidden` | `Sequence[str]` | `factory: tuple` |

### `PromptInjectionDefender`

[能力文档](../docs/harness/prompt-injection-defender.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `prompt-injection-defender`）。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `defense` | `PromptDefense \| None` | `None` |
| `block_high_risk` | `bool \| None` | `None` |
| `semantic_detection` | `bool` | `False` |
| `tool_filter` | `ToolSelector[AgentDepsT]` | `'all'` |
| `on_detection` | `OnDetection[AgentDepsT] \| None` | `None` |
| `blocked_message` | `str` | `_DEFAULT_BLOCKED_MESSAGE` |

### `ToolCallJudge`

[能力文档](../docs/harness/tool-call-judge.md)。

`model` 和 `question` 都必填。评审会增加模型调用；配置本地评审模型时传相应 Model 对象。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `model` | `Model \| KnownModelName \| str` | 必填 |
| `question` | `str` | 必填 |
| `tools` | `ToolSelector[AgentDepsT]` | `'all'` |
| `include_conversation` | `bool` | `False` |
| `conversation_window` | `int` | `4000` |
| `on_uncertain` | `Literal['block', 'allow', 'ask']` | `'block'` |
| `denial_message` | `str` | `'The call to \`{tool_name}\` was blocked by a tool-call judge. Do not retry it; continue without it and tell the user the call was blocked.'` |
| `on_verdict` | `Callable[[ToolCallVerdict], None] \| None` | `None` |

### `TrajectoryJudge`

[能力文档](../docs/harness/trajectory-judge.md)。

按轨迹检查运行过程，会产生额外模型调用。使用明确配置的本地 `model` 或 `agent`。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `model` | `Model \| KnownModelName \| str \| None` | `None` |
| `instructions` | `str \| None` | `None` |
| `agent` | `Agent[None, object] \| None` | `None` |
| `every` | `int` | `10` |
| `window` | `int` | `20000` |
| `name` | `str \| None` | `None` |
| `on_verdict` | `Callable[[TrajectoryVerdict], None] \| None` | `None` |

## 上下文压缩与输出限制

### `ClampOversizedMessages`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `max_part_tokens` | `int \| None` | `None` |
| `max_part_chars` | `int \| None` | `None` |
| `keep_head_chars` | `int` | `2000` |
| `keep_tail_chars` | `int` | `2000` |
| `clamp_tool_call_args` | `bool` | `True` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |

### `ClearToolResults`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `max_messages` | `int \| None` | `None` |
| `max_tokens` | `int \| None` | `None` |
| `keep_pairs` | `int` | `3` |
| `placeholder` | `str` | `'[tool result cleared]'` |
| `exclude_tools` | `frozenset[str]` | `frozenset()` |
| `clear_tool_inputs` | `bool` | `False` |
| `min_clear_tokens` | `int \| None` | `None` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `max_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |

### `DeduplicateFileReads`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `file_key` | `Callable[[ToolCallPart], str \| None]` | 必填 |
| `placeholder` | `str` | `'[superseded file read]'` |
| `max_messages` | `int \| None` | `None` |
| `max_tokens` | `int \| None` | `None` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `max_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |

### `SlidingWindowCompaction`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `max_messages` | `int \| None` | `None` |
| `max_tokens` | `int \| None` | `None` |
| `keep_messages` | `int` | `40` |
| `keep_tokens` | `int \| None` | `None` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `preserve_first_user_message` | `bool` | `True` |
| `receipts` | `bool` | `False` |
| `max_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |

### `SummarizingCompaction`

[能力文档](../docs/harness/compaction.md)。

`model=None` 复用运行模型；指定模型可以独立配置摘要模型。阈值、保留消息数和上下文窗口应与实际本地模型容量匹配。

通用参数默认值：`id='summarizing_compaction'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `model` | `str \| Model \| None` | `None` |
| `max_messages` | `int \| None` | `None` |
| `max_tokens` | `int \| None` | `None` |
| `keep_messages` | `int` | `20` |
| `keep_tokens` | `int \| None` | `None` |
| `summary_prompt` | `str` | `_DEFAULT_SUMMARY_PROMPT` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `preserve_first_user_message` | `bool` | `True` |
| `incremental` | `bool` | `True` |
| `bridge_prefix` | `bool` | `False` |
| `keep_user_messages` | `bool` | `False` |
| `keep_user_messages_max_chars` | `int` | `20000` |
| `receipts` | `bool` | `False` |
| `model_settings` | `ModelSettings \| None` | `None` |
| `event_stream_handler` | `EventStreamHandler[object] \| None` | `None` |
| `summarization_capabilities` | `Sequence[AbstractCapability[None]]` | `()` |
| `max_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |
| `instructions` | `str` | `'You are a context summarization assistant. Extract the most important information from conversations.'` |
| `tool_return_max_chars` | `int \| None` | `500` |

### `TieredCompaction`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `tiers` | `Sequence[CompactionStrategy[AgentDepsT]]` | 必填 |
| `target_tokens` | `int \| None` | `None` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `target_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |

### `FallbackCompaction`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `fallback_chain` | `Sequence[CompactionStrategy[AgentDepsT]]` | 必填 |
| `fallback_on` | `tuple[type[Exception], ...]` | `(<class 'pydantic_ai.exceptions.ModelAPIError'>, <class 'pydantic_ai.exceptions.FallbackExceptionGroup'>)` |
| `max_tokens` | `int \| None` | `None` |
| `max_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |

### `ReportContextUsage`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `on_usage` | `Callable[[ContextUsage], None \| Awaitable[None]] \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |

### `WarnNearLimits`

[能力文档](../docs/harness/compaction.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `max_iterations` | `int \| None` | `None` |
| `max_context_tokens` | `int \| None` | `None` |
| `max_total_tokens` | `int \| None` | `None` |
| `warn_on` | `list[WarningKind] \| None` | `None` |
| `warning_threshold` | `float` | `0.7` |
| `critical_remaining_iterations` | `int` | `3` |
| `max_context_fraction` | `float \| None` | `None` |
| `context_window` | `int \| None` | `None` |
| `fallback_context_window` | `int` | `200000` |

### `WarnOnCacheBusts`

[能力文档](../docs/harness/warn-on-cache-busts.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `collapse_ratio` | `float \| None` | `None` |
| `min_prefix_tokens` | `int \| None` | `None` |
| `cache_ttl_seconds` | `float \| None` | `None` |
| `min_missed_ratio` | `float` | `0.05` |
| `min_missed_tokens` | `int` | `2000` |

### `ToolOutputLimits`

[能力文档](../docs/harness/tool-output-limits.md)。

默认 bands 为 `[Band(over=10000, action=Spill(then=Truncate()))]`。`Spill` 使用的默认 workspace 存储、`Summarize` 使用的模型及各 action 的嵌套参数见能力文档。

通用参数默认值：`id='tool_output_limits'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `bands` | `Sequence[Band]` | `每实例新建 [Band(over=10000, action=Spill(then=Truncate()))]` |
| `per_tool` | `Mapping[str, Sequence[Band]]` | `factory: dict[str, Sequence[Band]]` |
| `tool_filter` | `ToolSelector[AgentDepsT]` | `'all'` |
| `over_tokens` | `bool` | `False` |
| `tokenizer` | `Callable[[str], int] \| None` | `None` |
| `store` | `OverflowStore \| WorkspaceStore \| None` | `None` |
| `strip_ansi` | `bool` | `False` |
| `summary_prompt` | `str` | `_DEFAULT_SUMMARY_PROMPT` |
| `serializer` | `Serializer \| None` | `None` |

## 代码执行、浏览器与生成能力

### `CodeMode`

[能力文档](../docs/harness/code-mode.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `code-mode`）。

需要 `pydantic-monty`；`os_access`、`mount` 与 `resource_limits` 的配置对象见文档。参数列全不代表各选项可以任意同时启用。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `tools` | `ToolSelector[AgentDepsT]` | `'all'` |
| `max_retries` | `int` | `3` |
| `max_tool_calls` | `int` | `100` |
| `os_access` | `CodeModeOS \| None` | `None` |
| `mount` | `CodeModeMount \| None` | `None` |
| `resource_limits` | `CodeModeResourceLimits \| Literal['unlimited'] \| None` | `None` |
| `eager` | `bool` | `False` |
| `speculate` | `Sequence[str] \| Literal['declared'] \| None` | `None` |
| `monty_sandbox_url` | `str \| None` | `None` |
| `dynamic_catalog` | `bool` | `False` |

### `DynamicWorkflow`

[能力文档](../docs/harness/dynamic-workflow.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `dynamic-workflow`）。

需要 `pydantic-monty`；`agents` 必填，可以为每个工作流 Agent 配置不同的本地模型。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `agents` | `Sequence[AbstractAgent[AgentDepsT, object] \| WorkflowAgent[AgentDepsT]]` | 必填 |
| `tool_name` | `str` | `'run_workflow'` |
| `max_agent_calls` | `int` | `50` |
| `max_retries` | `int` | `3` |
| `forward_usage` | `bool` | `True` |
| `inherit_model` | `bool` | `False` |
| `sub_agent_usage_limits` | `UsageLimits \| None` | `None` |
| `resource_limits` | `WorkflowResourceLimits \| Literal['unlimited'] \| None` | `None` |

### `BrowserUse`

[能力文档](../docs/harness/browser-use.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `browser-use`）。

需要 `browser-use` 和可用浏览器。明确设置 `llm` 才能让子代理使用指定本地模型；`llm=None` 会使用 browser-use 的默认模型选择。文本模型可选择 `use_vision=False`。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `llm` | `ChatModelInput \| None` | `None` |
| `browser_profile` | `BrowserProfile \| None` | `None` |
| `allowed_domains` | `list[str] \| None` | `None` |
| `block_ip_addresses` | `bool` | `True` |
| `headless` | `bool \| None` | `None` |
| `max_steps` | `int` | `50` |
| `use_vision` | `bool \| Literal['auto']` | `True` |
| `output_schema` | `type[BaseModel] \| None` | `None` |
| `sensitive_data` | `dict[str, str \| dict[str, str]] \| None` | `None` |
| `extend_system_message` | `str \| None` | `None` |
| `agent_settings` | `BrowserAgentSettings \| None` | `None` |
| `session_scope` | `Literal['call', 'agent']` | `'call'` |
| `cdp_url` | `str \| None` | `None` |
| `guidance` | `str \| None` | `None` |
| `browser_agent` | `BrowserAgentFactory \| None` | `None` |

### `CapabilityCreation`

[能力文档](../docs/harness/capability-creation.md)。

通用参数默认值：`id='capability_creation'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `directory` | `Path` | 必填 |
| `guidance` | `str \| None` | `None` |

### `Macroscope`

[能力文档](../docs/harness/macroscope.md)。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `base` | `str \| None` | `None` |
| `command` | `str` | `'macroscope'` |
| `cwd` | `str \| Path \| None` | `None` |
| `timeout` | `float` | `600.0` |
| `guidance` | `str \| None` | `None` |

## 搜索、托管提示词与外部应用

### `ExaSearch`

[能力文档](../docs/harness/exa-search.md)。

通用参数默认值：`id='exa_search'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `num_results` | `int` | `5` |
| `max_text_chars` | `int` | `10000` |
| `text_summary` | `bool \| str` | `False` |
| `include_deep_search` | `bool` | `False` |
| `include_domains` | `Sequence[str]` | `factory: list[str]` |
| `exclude_domains` | `Sequence[str]` | `factory: list[str]` |
| `guidance` | `str \| None` | `None` |
| `client` | `ExaClient \| None` | `None` |
| `native` | `bool` | `False` |

### `ExaAgent`

[能力文档](../docs/harness/exa-search.md)。

通用参数默认值：`id='exa_agent'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `effort` | `AgentEffort \| None` | `None` |
| `execution` | `Literal['inline', 'external']` | `'inline'` |
| `output_schema` | `type[BaseModel] \| dict[str, object] \| None` | `None` |
| `system_prompt` | `str \| None` | `None` |
| `poll_interval` | `int` | `1000` |
| `timeout_ms` | `int` | `3600000` |
| `guidance` | `str \| None` | `None` |
| `runs` | `ExaAgentRuns \| None` | `None` |

### `YouSearch`

[能力文档](../docs/harness/youdotcom.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `youdotcom`）。

`include_domains` 不能与 `exclude_domains` 或 `boost_domains` 同用。`native=False` 使用 You.com 服务，不是离线搜索。

通用参数默认值：`id='you_search'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `num_results` | `int` | `10` |
| `extraction_mode` | `ExtractionModeName` | `'highlights'` |
| `max_text_chars` | `int` | `10000` |
| `include_domains` | `list[str]` | `factory: list[str]` |
| `exclude_domains` | `list[str]` | `factory: list[str]` |
| `boost_domains` | `list[str]` | `factory: list[str]` |
| `freshness` | `str \| None` | `None` |
| `country` | `str \| None` | `None` |
| `guidance` | `str \| None` | `None` |
| `timeout_ms` | `int` | `60000` |
| `native` | `bool` | `False` |
| `client` | `YouClient \| None` | `None` |

### `YouResearch`

[能力文档](../docs/harness/youdotcom.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `youdotcom`）。

`include_domains` 不能与 `exclude_domains` 或 `boost_domains` 同用；`research_effort='lite'` 不能搭配 `output_schema`。该能力访问 You.com 服务。

通用参数默认值：`id='you_research'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `research_effort` | `ResearchEffortName` | `'standard'` |
| `finance_effort` | `FinanceEffortName` | `'deep'` |
| `include_domains` | `list[str]` | `factory: list[str]` |
| `exclude_domains` | `list[str]` | `factory: list[str]` |
| `boost_domains` | `list[str]` | `factory: list[str]` |
| `freshness` | `str \| None` | `None` |
| `country` | `str \| None` | `None` |
| `output_schema` | `Mapping[str, object] \| None` | `None` |
| `guidance` | `str \| None` | `None` |
| `timeout_ms` | `int` | `600000` |
| `client` | `YouClient \| None` | `None` |

### `ManagedPrompt`

[能力文档](../docs/harness/managed-prompt.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `logfire[variables]`）。

需要 Logfire managed variables 的可选依赖与服务配置。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `name` | `str \| Variable[str]` | 必填 |
| `default` | `str \| None` | `None` |
| `label` | `str \| None` | `None` |
| `targeting_key` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `attributes` | `Mapping[str, Any] \| Callable[[RunContext[AgentDepsT]], Mapping[str, Any] \| None] \| None` | `None` |
| `render_template` | `bool` | `False` |
| `logfire_instance` | `Logfire \| None` | `None` |

### `DayAI`

[能力文档](../docs/harness/day-ai.md)。

通用参数默认值：`id='day_ai'`；`description='Work inside a Day AI workspace: search and update CRM records, read meeting context, and draft emails.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `auth` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `include_instructions` | `bool` | `True` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `Grain`

[能力文档](../docs/harness/grain.md)。

通用参数默认值：`id='grain'`；`description='Search and read Grain meetings: transcripts, notes, people, companies, and deals.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `auth` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `read_only` | `bool` | `False` |
| `include_instructions` | `bool` | `True` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `Ordinal`

[能力文档](../docs/harness/ordinal.md)。

通用参数默认值：`id='ordinal'`；`description='Work inside an Ordinal workspace: draft, schedule, and analyze social posts.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `auth` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `include_instructions` | `bool` | `True` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `PostHog`

[能力文档](../docs/harness/posthog.md)。

通用参数默认值：`id='posthog'`；`description='Query PostHog analytics and manage feature flags, experiments, and dashboards.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `auth` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `read_only` | `bool` | `False` |
| `features` | `str \| Sequence[str] \| None` | `None` |
| `include_instructions` | `bool` | `True` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `Pylon`

[能力文档](../docs/harness/pylon.md)。

通用参数默认值：`id='pylon'`；`description='Work in Pylon: search, read, create, and update support issues, look up and update accounts, and look up contacts.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `auth` | `str \| Callable[[RunContext[AgentDepsT]], str \| None] \| None` | `None` |
| `read_only` | `bool` | `False` |
| `include_instructions` | `bool` | `True` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `StackOne`

[能力文档](../docs/harness/stackone.md)。

通用参数默认值：`id=None`；`description='Use actions from a linked business application through StackOne.'`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `account_id` | `str` | 必填 |
| `api_key` | `str \| None` | `None` |
| `base_url` | `str` | `'https://api.stackone.com'` |
| `actions` | `str \| Sequence[str]` | `()` |
| `tool_mode` | `ToolMode \| None` | `None` |
| `include_instructions` | `bool` | `True` |
| `metadata` | `Mapping[str, object] \| None` | `None` |
| `client` | `MCPToolsetClient \| None` | `None` |

### `LocalStack`

[能力文档](../docs/harness/localstack.md)。

需要 LocalStack 服务与 AWS CLI；`manage_container=True` 还会使用 Docker。

通用参数默认值：`id='localstack'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `endpoint_url` | `str` | `'http://localhost.localstack.cloud:4566'` |
| `region` | `str` | `'us-east-1'` |
| `access_key_id` | `str` | `'test'` |
| `secret_access_key` | `str` | `'test'` |
| `allowed_services` | `Sequence[str]` | `factory: list[str]` |
| `denied_services` | `Sequence[str]` | `factory: list[str]` |
| `default_timeout` | `float` | `60.0` |
| `max_output_chars` | `int` | `50000` |
| `aws_cli_path` | `str` | `'aws'` |
| `manage_container` | `bool` | `False` |
| `image` | `str` | `'localstack/localstack'` |
| `host_address` | `str` | `'127.0.0.1'` |
| `service_port_range` | `str \| None` | `None` |
| `mount_docker_socket` | `bool` | `False` |
| `container_name` | `str \| None` | `None` |
| `container_env` | `Mapping[str, str]` | `factory: dict[str, str]` |
| `docker_path` | `str` | `'docker'` |
| `startup_timeout` | `float` | `120.0` |
| `include_instructions` | `bool` | `True` |

## 工作区与沙箱

### `BubblewrapSandbox`

[能力文档](../docs/harness/bubblewrap-sandbox.md)。

依赖 Linux 的 bubblewrap；Windows 本地示例不默认启用。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `wrapped` | `AbstractCapability[AgentDepsT]` | 必填 |
| `network` | `bool` | `False` |
| `bwrap_args` | `Sequence[str]` | `()` |

### `E2BSandbox`

[能力文档](../docs/harness/e2b-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `e2b`）。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `template` | `str \| None` | `None` |
| `allow_internet_access` | `bool` | `True` |
| `sandbox_timeout` | `int` | `3600` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |

### `ModalSandbox`

[能力文档](../docs/harness/modal-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `modal`）。

`workdir` 已弃用，使用 `working_dir`。`**removed_arguments: Never` 仅承接历史参数的迁移诊断，不是可自由添加配置的扩展接口。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `image` | `str \| modal.Image \| None` | `None` |
| `app_name` | `str` | `'pydantic-ai-harness'` |
| `create_app_if_missing` | `bool` | `True` |
| `sandbox_timeout` | `int` | `86400` |
| `idle_timeout` | `int \| None` | `None` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |
| `warn_if_no_tools` | `bool` | `True` |
| `workdir` | `str \| None` | `None` |
| `**removed_arguments` | `Never` | `<optional>` |

### `SpritesSandbox`

[能力文档](../docs/harness/sprites-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `sprites`）。

通用参数默认值：`id=None`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `client` | `AsyncSpritesClient \| None` | `None` |
| `runtime` | `str \| None` | `None` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |

### `SSHWorkspace`

[能力文档](../docs/harness/ssh-workspace.md)。

通用参数默认值：`id='ssh_workspace'`；`description=None`；`defer_loading=False`。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `destination` | `str` | 必填 |
| `working_dir` | `str \| None` | `None` |
| `read_only` | `bool` | `False` |
| `env` | `Mapping[str, str] \| None` | `None` |
| `ssh_args` | `Sequence[str]` | `()` |

## 顶层导出的辅助对象

### `SubAgent`

[能力文档](../docs/harness/subagents.md)。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `agent` | `AbstractAgent[AgentDepsT, Any]` | 必填 |
| `name` | `str \| None` | `None` |
| `description` | `str \| None` | `None` |
| `models` | `Sequence[str] \| None` | `None` |
| `usage_limits` | `UsageLimits \| None` | `None` |
| `timeout_seconds` | `float \| None` | `None` |
| `max_calls` | `int \| None` | `None` |
| `on_failure` | `str \| None` | `None` |
| `contain_errors` | `bool \| None` | `None` |
| `read_only` | `bool` | `False` |

### `GuardrailResult`

[能力文档](../docs/harness/guardrails.md)。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `action` | `Literal['allow', 'block', 'replace', 'retry', 'approve']` | 必填 |
| `message` | `str \| None` | `None` |
| `replacement` | `object` | `<unset>` |

### `BubblewrapWorkspace`

[能力文档](../docs/harness/bubblewrap-sandbox.md)。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `wrapped` | `Workspace` | 必填 |
| `network` | `bool` | `False` |
| `bwrap_args` | `Sequence[str]` | `()` |

### `E2BSandboxBackend`

[能力文档](../docs/harness/e2b-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `e2b`）。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `sandbox` | `e2b.AsyncSandbox \| None` | `None` |
| `ref` | `WorkspaceRef \| None` | `None` |
| `template` | `str \| None` | `None` |
| `allow_internet_access` | `bool` | `True` |
| `sandbox_timeout` | `int` | `3600` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |

### `ModalSandboxBackend`

[能力文档](../docs/harness/modal-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `modal`）。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `sandbox` | `modal.Sandbox \| None` | `None` |
| `ref` | `WorkspaceRef \| None` | `None` |
| `image` | `str \| modal.Image \| None` | `None` |
| `app_name` | `str` | `'pydantic-ai-harness'` |
| `create_app_if_missing` | `bool` | `True` |
| `sandbox_timeout` | `int` | `86400` |
| `idle_timeout` | `int \| None` | `None` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |

### `SpritesSandboxBackend`

[能力文档](../docs/harness/sprites-sandbox.md)。 参数由本地源码 AST 核对，未通过运行时导入核对（缺少 `sprites`）。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `sandbox` | `AsyncSprite \| None` | `None` |
| `client` | `AsyncSpritesClient \| None` | `None` |
| `ref` | `WorkspaceRef \| None` | `None` |
| `runtime` | `str \| None` | `None` |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |

### `SSHWorkspaceBackend`

[能力文档](../docs/harness/ssh-workspace.md)。

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `destination` | `str` | 必填 |
| `working_dir` | `str \| None` | `None` |
| `env` | `Mapping[str, str] \| None` | `None` |
| `ssh_args` | `Sequence[str]` | `()` |

## 其他顶层导出项

这些名字不是可加入 `capabilities` 的构造参数：

| 导出项 | 用途 |
| --- | --- |
| `DEFAULT_RESEARCHER_INSTRUCTIONS` | Researcher 默认提示词。 |
| `LLM_API_KEY_ENV_PATTERNS` | Shell 可使用的 LLM 凭据环境变量匹配模式。 |
| `READ_ONLY_TOOL_NAMES` | FileSystem 的只读工具名集合。 |
| `InputGuardrailFunc`、`OutputGuardrailFunc` | Guardrail 回调的类型别名。 |
| `GuardrailError`、`InputBlocked`、`OutputBlocked` | Guardrail 异常。 |
| `HarnessDeprecationWarning`、`MCPReadOnlyNoToolsWarning` | 弃用和 MCP 配置警告类型。 |

旧名 `InputGuard`、`OutputGuard` 等兼容别名不作为新示例的配置入口。
