# Harness 源码调试

完整流程入口是 `python -m harness_example.main`，无需参数。同文件的 `DEEPSEEK_API_KEY` 有值时连接 DeepSeek，否则连接本地 Ollama。先在 `create_model`、`build_agent` 放断点，再进入核心和 Harness 源码。完整入口先执行包含任务拆解的 29 步工具流程，再执行跨会话记忆和长历史专题。

## 直接 F5 启动（推荐）

[launch.json](../.vscode/launch.json) 只保留两个 `request: "launch"` 入口，F5 直接启动本地 Python 和调试器：

| 配置 | 启动入口 |
| --- | --- |
| **Debug Harness** | `harness_example.main`，完整 Harness 流程 |
| **Debug Agent** | [pydantic_agent_example/main.py](../pydantic_agent_example/main.py)，基础 Agent 示例 |

1. 在普通 VS Code 窗口打开仓库，安装 Python 和 Python Debugger 扩展。
2. 打开左侧“运行和调试”（Ctrl+Shift+D），选择 **Debug Harness**。
3. 使用 DeepSeek 时，在根目录 `.env` 中设置 `DEEPSEEK_API_KEY=你的密钥`；留空使用本地 Ollama。默认接口为 `http://localhost:11434/v1`，也可在 `.env` 设置 `OLLAMA_BASE_URL` 和 `OLLAMA_MODEL`。
4. 按 F5 自动启动，并在入口暂停（`stopOnEntry: true`）。在 `main()` 或 `build_agent()` 设置断点后，F5 继续、F10 单步、F11 进入函数。

Windows 使用 `${workspaceFolder}/.venv/Scripts/python.exe`，Linux/macOS 使用 `${workspaceFolder}/.venv/bin/python`。完整例子无需 WSL；Windows 平台差异集中在 `main.py` 的 `NativeWorkspaceBackend`、`NativeWorkspace` 和 `NativeShell`。

配置使用 `justMyCode: false`。源码依赖采用 editable 安装，因此能进入当前仓库，而不是另一份已发布的包。

**Debug Harness** 已启用 `subProcess: true`。在 `main.py` 的 `mcp_add()` 内 `return a + b` 直接打断点，服务端会作为子进程调试会话出现；F11 不会跨 RPC 自动跳进服务端。工具请求超时为 300 秒，暂停超过这个时间后需重新运行。

## 选择专题与运行测试

所有专题都在 [main.py](main.py)。默认 `main()` 依次调用 `run_example()`、`demonstrate_memory()` 和 `demonstrate_history()`。只学习某个专题时，临时替换底部 `main()` 的函数体，再用 **Debug Harness** F5；例如只观察 MCP：

~~~python
async def main() -> None:
    await run_mcp()
~~~

RAG 可换为 `await run_rag('Harness 怎样接入外部知识？')`；进阶实验可换为 `await run_lesson('code-mode', offline=True)`。保留文件末尾的启动逻辑，它还负责 MCP 服务端子进程的内部 `--mcp-server` 分流。观察完成后恢复默认流程。

在仓库根目录运行 `just harness-test`，执行本目录全部测试，不请求真实模型；测试文件仍按专题独立保留。

示例已移除 `print` 和自定义日志输出。调试时在变量面板观察 `result`、`ctx.deps`、消息和工具结果，也可以打开 `output/` 中保存的运行产物。

## 源码路线

| 顺序 | 文件 / 符号 | 看什么 |
| --- | --- | --- |
| 1 | [main.py](main.py)：`build_agent`、`prepare_workspace` | 先看 `Agent(capabilities=[...])` 中直接挂载的 Planning 和其他能力，再看工作区、存储与依赖 |
| 2 | [main.py](main.py)：`Walkthrough`、`preserve_plan_reminder`、`guide_current_step` | 按步骤准备工具范围、保留并恢复当次计划提醒、追加教学提示、成功执行后推进 |
| 3 | [Agent.iter](../pydantic_ai_slim/pydantic_ai/agent/__init__.py) | deps、conversation、usage 与能力进入执行图 |
| 4 | [CombinedCapability](../pydantic_ai_slim/pydantic_ai/capabilities/combined.py) | 组合钩子的调用顺序 |
| 5 | [ModelRequestNode / CallToolsNode](../pydantic_ai_slim/pydantic_ai/_agent_graph.py) | 请求模型、解析响应、执行工具、重试 |
| 6 | [FileSystem](../src/pydantic_ai_harness/pydantic_ai_harness/filesystem/_toolset.py)、[本地适配层](main.py)、[POSIX Shell](../src/pydantic_ai_harness/pydantic_ai_harness/shell/_toolset.py) | Windows 文件操作进入 NativeWorkspaceBackend，命令进入 NativeShell；POSIX 使用内置实现 |
| 7 | [Planning](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_capability.py)、[Memory](../src/pydantic_ai_harness/pydantic_ai_harness/memory/_capability.py) | 父子任务、依赖与状态、计划及记忆的提示注入 |
| 8 | [Skills](../src/pydantic_ai_harness/pydantic_ai_harness/skills/_capability.py) | 发现技能与延迟加载 |
| 9 | [SubAgents](../src/pydantic_ai_harness/pydantic_ai_harness/subagents/_toolset.py) | 子 Agent 的独立历史与父任务用量 |
| 10 | [ToolOutputLimits](../src/pydantic_ai_harness/pydantic_ai_harness/tool_output_limits/_capability.py)、[Compaction](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/) | 新工具结果限长与旧历史压缩的区别 |
| 11 | [StepPersistence](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_capability.py)、[continue_run](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_helpers.py) | 保存快照、读回消息、后续 run |
| 12 | [run_interactive](../pydantic_harness_example/main.py)、[AskUserToolset.ask_user_question](../src/pydantic_ai_harness/pydantic_ai_harness/ask_user/_toolset.py) | 延迟请求、终端收集回答、同一 conversation 恢复 |
| 13 | [main.py](main.py)：`build_memory_agent`、`demonstrate_memory` | 新 Agent、新 conversation、相同用户 namespace，观察持久记忆注入 |
| 14 | [main.py](main.py)：`load_history`、`capture_window`、`compact_now` 调用处 | 对比一万条档案与模型实际窗口，进入 [SummarizingCompaction](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/_summarizing_compaction.py) 看摘要更新 |
| 15 | [main.py](main.py)：`KnowledgeRAG.get_toolset` 中的 `search_knowledge` | 从工具进入 `ctx.deps.retrieval`，查看片段和来源怎样返回模型 |
| 16 | [main.py](main.py)：`create_mcp_capability`、`run_mcp`、`mcp_add` | 同文件子进程的工具发现、跨进程调用与结果回传；核心入口是 [MCPToolset](../pydantic_ai_slim/pydantic_ai/mcp.py) |

建议展开 `ctx.deps`、`ctx.usage`、工具参数、`messages` 和工具结果。能力列表不是只从上到下执行一次的流水线：不同钩子由核心在不同时机调用。

## 任务拆解的断点顺序

用 **Debug Harness** 运行完整流程，在下列位置观察 `study` 父任务和 `research`、`practice`、`report` 三个子任务。任务结构与固定 ID 由教学提示给定，模型生成工具参数；真实业务工具成功后，导览才允许推进到相应任务的完成更新。

| 断点 | 观察内容 |
| --- | --- |
| [main.py](main.py) 的 `build_agent`、`Walkthrough` | `enable_subtasks=True` 与五个计划工具；业务成功后怎样开放状态更新步骤 |
| [PlanningToolset.write_plan](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_toolset.py) | 模型传入的四个 `PlanItem`，检查 `id`、`parent_id` 与初始 `status` |
| 同文件的 `set_dependency`、`get_available_tasks` | `practice` 依赖 `research`、`report` 依赖 `practice`；状态变为 `blocked` 后不进入可用列表 |
| 同文件的 `update_task_status`、`_sync_dependency_blocks` | 阶段从 `in_progress` 到 `completed`，下一项从 `blocked` 回到 `pending` |
| [SqlitePlanStore.set_items / update_item](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_store.py) | 整表创建与单项更新怎样保存到 `plan.db` |
| [Planning.wrap_model_request](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_capability.py) | 读取最新计划，生成当前请求的 `<plan-reminder>` |
| [main.py](main.py) 的 `preserve_plan_reminder` | 在压缩前将当次提醒暂存到 `ctx.deps.plan_reminder` |
| [ClampOversizedMessages.before_model_request](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/_clamp_oversized_messages.py) | 从 `ctx.messages` 重建请求，观察临时计划提醒被覆盖 |
| [main.py](main.py) 的 `guide_current_step` | 压缩后若提醒缺失，恢复同一个 `UserPromptPart`，再追加教学提示 |
| [PlanningToolset.read_plan_tree](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_toolset.py) | 模型工具名 `read_plan` 在子任务模式下映射到此方法，`hierarchical=True` 渲染父子结构 |

这两个公开 `Hooks` 是示例针对当前 Planning 与压缩组合的衔接，没有修改库。保留的是 Planning 当次生成的提醒，不重新生成计划，也不将提醒加入 `ctx.messages`；对比 `request_context.messages` 与持久消息历史即可观察区别。

子任务完成只会解除后续依赖，不会自动执行下一项，也不会自动把父任务标为完成。观察最后一次 `update_task_status(task_id='study', status='completed')`，确认父任务由模型显式更新。

断点中展开每个任务的 `id`、`parent_id`、`depends_on`、`status`。运行后打开 `output/demo/plan_history.json`，逐条比较 `{tool, items}`；`plan.json` 保存最终四项任务，`plan.db` 是实际存储。完整拆解结构见 [任务拆解、依赖与进度](README.md#任务拆解依赖与进度)。

## 三个进阶实验

在 `main()` 中调用 `await run_lesson('code-mode')`、`await run_lesson('workflow')` 或 `await run_lesson('background')`，再用 **Debug Harness** F5。三个实验函数都在 [main.py](main.py)，对照以下框架源码阅读：

| 实验 | 源码 |
| --- | --- |
| `code-mode` | [CodeMode 工具](../src/pydantic_ai_harness/pydantic_ai_harness/code_mode/_toolset.py)：Monty 脚本与宿主工具调用 |
| `workflow` | [DynamicWorkflow 工具](../src/pydantic_ai_harness/pydantic_ai_harness/dynamic_workflow/_toolset.py)：脚本调度子 Agent |
| `background` | [BackgroundTools](../src/pydantic_ai_harness/pydantic_ai_harness/background_tools/_capability.py)：后台任务、消息注入与资源清理 |

Monty 的宿主调度和工具函数是 Python 源码；沙箱内部是 Rust 解释器。`run_lesson(..., offline=True)` 固定模型决策，便于断点复现；默认通过 `create_model()` 选择 DeepSeek 或本地 Ollama。

本目录进阶组件同样使用本地 `.venv`。
