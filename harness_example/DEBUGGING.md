# Harness 源码调试

完整流程入口是 `python -m harness_example.main`，无需参数。[model_config.py](model_config.py) 的 `DEEPSEEK_API_KEY` 有值时连接 DeepSeek，否则连接本地 Ollama。先在 `create_model`、`build_agent` 放断点，再进入核心和 Harness 源码。完整入口也会执行跨会话记忆和长历史专题。

## 直接 F5 启动（推荐）

[launch.json](../.vscode/launch.json) 的第一项 **Python: Harness 直接启动 (F5 / Local)** 使用 `request: "launch"`。F5 会负责启动本地 Python 和调试器，不需要先开终端运行命令。

1. 在普通 VS Code 窗口打开仓库，安装 Python 和 Python Debugger 扩展。
2. 打开左侧“运行和调试”（Ctrl+Shift+D），选择第一项 **Python: Harness 直接启动 (F5 / Local)**。
3. 使用 DeepSeek 时，在根目录 `.env` 中设置 `DEEPSEEK_API_KEY=你的密钥`；留空使用本地 Ollama。默认接口为 `http://localhost:11434/v1`，也可在 `.env` 设置 `OLLAMA_BASE_URL` 和 `OLLAMA_MODEL`。
4. 按 F5 自动启动，并在入口暂停（`stopOnEntry: true`）。在 `main()` 或 `build_agent()` 设置断点后，F5 继续、F10 单步、F11 进入函数。

Windows 使用 `${workspaceFolder}/.venv/Scripts/python.exe`，Linux/macOS 使用 `${workspaceFolder}/.venv/bin/python`。完整例子无需 WSL；Windows 平台差异集中在 [local_workspace.py](local_workspace.py)。

配置使用 `justMyCode: false`。源码依赖采用 editable 安装，因此能进入当前仓库，而不是另一份已发布的包。

单独学习时可选 **Python: Harness 记忆与历史 (Local)**、**Python: Harness 外部 RAG (Local)**、**Python: Harness MCP 客户端与服务端 (Local)**，都使用本地 `.venv`，不传命令行参数。

完整流程和 MCP 配置已启用 `subProcess: true`。在 [mcp_server.py](mcp_server.py) 的 `return a + b` 直接打断点，服务端会作为子进程调试会话出现；F11 不会跨 RPC 自动跳进服务端。工具请求超时为 300 秒，暂停超过这个时间后需重新运行。

## 从 just 附加调试

1. 在仓库根目录执行 `just harness-debug`。它会启动本地 Python，在 `127.0.0.1:5678` 监听并等待；尚未连接时不会执行例子。
2. 用 VS Code 打开同一仓库，在 `main.py` 的 `main` 或 `build_agent` 中设置断点。
3. 选择 **Python: Harness 附加 just 调试 (Local)**，按 F5。之后可以继续、单步，并进入 MCP 子进程。
4. 停止调试后结束启动命令；重新调试时重新运行 `just harness-debug`。同一时间只启动一个使用 5678 端口的会话。

附加配置的模型与 Python 设置由启动 `just` 的终端及根目录 `.env` 提供。

只调试测试时，选择 **Python: Harness 测试 (pytest / Local)** 并按 F5。它执行 `harness_example` 的测试，不请求真实模型；普通运行同一组测试使用 `just harness-test`。

示例已移除 `print` 和自定义日志输出。调试时在变量面板观察 `result`、`ctx.deps`、消息和工具结果，也可以打开 `output/` 中保存的运行产物。

## 源码路线

| 顺序 | 文件 / 符号 | 看什么 |
| --- | --- | --- |
| 1 | [main.py](main.py)：`prepare_workspace`、`build_agent` | 工作区、存储、依赖与能力组合 |
| 2 | [main.py](main.py)：`Walkthrough`、`guide_current_step` | 按步骤准备工具范围、请求末尾教学提示、成功执行后推进 |
| 3 | [Agent.iter](../pydantic_ai_slim/pydantic_ai/agent/__init__.py) | deps、conversation、usage 与能力进入执行图 |
| 4 | [CombinedCapability](../pydantic_ai_slim/pydantic_ai/capabilities/combined.py) | 组合钩子的调用顺序 |
| 5 | [ModelRequestNode / CallToolsNode](../pydantic_ai_slim/pydantic_ai/_agent_graph.py) | 请求模型、解析响应、执行工具、重试 |
| 6 | [FileSystem](../src/pydantic_ai_harness/pydantic_ai_harness/filesystem/_toolset.py)、[本地适配层](local_workspace.py)、[POSIX Shell](../src/pydantic_ai_harness/pydantic_ai_harness/shell/_toolset.py) | Windows 文件操作进入 NativeWorkspaceBackend，命令进入 NativeShell；POSIX 使用内置实现 |
| 7 | [Planning](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_capability.py)、[Memory](../src/pydantic_ai_harness/pydantic_ai_harness/memory/_capability.py) | 工具、状态存储与提示注入 |
| 8 | [Skills](../src/pydantic_ai_harness/pydantic_ai_harness/skills/_capability.py) | 发现技能与延迟加载 |
| 9 | [SubAgents](../src/pydantic_ai_harness/pydantic_ai_harness/subagents/_toolset.py) | 子 Agent 的独立历史与父任务用量 |
| 10 | [ToolOutputLimits](../src/pydantic_ai_harness/pydantic_ai_harness/tool_output_limits/_capability.py)、[Compaction](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/) | 新工具结果限长与旧历史压缩的区别 |
| 11 | [StepPersistence](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_capability.py)、[continue_run](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_helpers.py) | 保存快照、读回消息、后续 run |
| 12 | [run_interactive](../pydantic_harness_example/main.py)、[AskUserToolset.ask_user_question](../src/pydantic_ai_harness/pydantic_ai_harness/ask_user/_toolset.py) | 延迟请求、终端收集回答、同一 conversation 恢复 |
| 13 | [memory_history.py](memory_history.py)：`build_memory_agent`、`demonstrate_memory` | 新 Agent、新 conversation、相同用户 namespace，观察持久记忆注入 |
| 14 | [memory_history.py](memory_history.py)：`load_history`、`capture_window`、`compact_now` 调用处 | 对比一万条档案与模型实际窗口，进入 [SummarizingCompaction](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/_summarizing_compaction.py) 看摘要更新 |
| 15 | [rag.py](rag.py)：`KnowledgeRAG.get_toolset` 中的 `search_knowledge` | 从工具进入 `ctx.deps.retrieval`，查看片段和来源怎样返回模型 |
| 16 | [mcp_client.py](mcp_client.py)：`create_mcp_capability`；[mcp_server.py](mcp_server.py)：`mcp_add` | 工具发现、跨进程调用、结果回传；核心入口是 [MCPToolset](../pydantic_ai_slim/pydantic_ai/mcp.py) |

建议展开 `ctx.deps`、`ctx.usage`、工具参数、`messages` 和工具结果。能力列表不是只从上到下执行一次的流水线：不同钩子由核心在不同时机调用。

## 三个进阶实验

先在 [advanced.py](advanced.py) 的对应实验放断点，再进入：

| 实验 | 源码 |
| --- | --- |
| `code-mode` | [CodeMode 工具](../src/pydantic_ai_harness/pydantic_ai_harness/code_mode/_toolset.py)：Monty 脚本与宿主工具调用 |
| `workflow` | [DynamicWorkflow 工具](../src/pydantic_ai_harness/pydantic_ai_harness/dynamic_workflow/_toolset.py)：脚本调度子 Agent |
| `background` | [BackgroundTools](../src/pydantic_ai_harness/pydantic_ai_harness/background_tools/_capability.py)：后台任务、消息注入与资源清理 |

Python 调试器可以单步进入 Monty 的宿主调度和工具函数；沙箱内部的 Rust 解释器不是 Python 源码。`--offline` 固定模型决策，适合断点复现；省略时连接本地 Ollama。

本目录进阶组件同样使用本地 `.venv`。调试列表中带“旧示例”的配置属于 `pydantic_harness_example`，其 Coder 组合仍有自己的平台要求，不影响本目录完整流程。
