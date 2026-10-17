# Harness 源码调试

完整流程入口是 `python -m harness_example.main`，无需参数。`main.py` 顶部的 `DEEPSEEK_API_KEY` 有值时连接 DeepSeek，否则连接本地 Ollama，执行逐步导览和快照续接。先在例子的 `create_model`、`build_agent` 放断点，再进入核心和 Harness 源码。

## F5

1. 安装 Microsoft 的 WSL 扩展，以 **Remote - WSL** 重新打开仓库。
2. 在 WSL 窗口安装 Python 和 Python Debugger 扩展。
3. 选择 **Python: Harness 完整流程 (DeepSeek / Ollama / WSL)**。使用 DeepSeek 时，在根目录 `.env` 中设置 `DEEPSEEK_API_KEY=你的密钥`；留空使用本地模型。
4. 输入 WSL Python 路径 `/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python`、本地模型和接口地址；后两项仅在 Key 为空时使用。
5. 设置断点，F5 继续、F10 单步、F11 进入函数。

Windows Ollama + WSL NAT 时，用 `ip -4 route show default` 的网关地址组成 `http://网关:11434/v1`。这台机器当前可用 `http://172.31.192.1:11434/v1`；WSL 重启后可能改变。

配置使用 `justMyCode: false`。源码依赖采用 editable 安装，因此能进入当前仓库，而不是另一份已发布的包。

## 源码路线

| 顺序 | 文件 / 符号 | 看什么 |
| --- | --- | --- |
| 1 | [main.py](main.py)：`prepare_workspace`、`build_agent` | 工作区、存储、依赖与能力组合 |
| 2 | [main.py](main.py)：`Walkthrough`、`guide_current_step` | 按步骤准备工具范围、请求末尾教学提示、成功执行后推进 |
| 3 | [Agent.iter](../pydantic_ai_slim/pydantic_ai/agent/__init__.py) | deps、conversation、usage 与能力进入执行图 |
| 4 | [CombinedCapability](../pydantic_ai_slim/pydantic_ai/capabilities/combined.py) | 组合钩子的调用顺序 |
| 5 | [ModelRequestNode / CallToolsNode](../pydantic_ai_slim/pydantic_ai/_agent_graph.py) | 请求模型、解析响应、执行工具、重试 |
| 6 | [FileSystem](../src/pydantic_ai_harness/pydantic_ai_harness/filesystem/_toolset.py)、[Shell](../src/pydantic_ai_harness/pydantic_ai_harness/shell/_toolset.py) | 文件/命令如何交给 workspace 后端 |
| 7 | [Planning](../src/pydantic_ai_harness/pydantic_ai_harness/planning/_capability.py)、[Memory](../src/pydantic_ai_harness/pydantic_ai_harness/memory/_capability.py) | 工具、状态存储与提示注入 |
| 8 | [Skills](../src/pydantic_ai_harness/pydantic_ai_harness/skills/_capability.py) | 发现技能与延迟加载 |
| 9 | [SubAgents](../src/pydantic_ai_harness/pydantic_ai_harness/subagents/_toolset.py) | 子 Agent 的独立历史与父任务用量 |
| 10 | [ToolOutputLimits](../src/pydantic_ai_harness/pydantic_ai_harness/tool_output_limits/_capability.py)、[Compaction](../src/pydantic_ai_harness/pydantic_ai_harness/compaction/) | 新工具结果限长与旧历史压缩的区别 |
| 11 | [StepPersistence](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_capability.py)、[continue_run](../src/pydantic_ai_harness/pydantic_ai_harness/step_persistence/_helpers.py) | 保存快照、读回消息、后续 run |
| 12 | [run_interactive](../pydantic_harness_example/main.py)、[AskUserToolset.ask_user_question](../src/pydantic_ai_harness/pydantic_ai_harness/ask_user/_toolset.py) | 延迟请求、终端收集回答、同一 conversation 恢复 |

建议展开 `ctx.deps`、`ctx.usage`、工具参数、`messages` 和工具结果。能力列表不是只从上到下执行一次的流水线：不同钩子由核心在不同时机调用。

## 三个进阶实验

先在 [advanced.py](advanced.py) 的对应实验放断点，再进入：

| 实验 | 源码 |
| --- | --- |
| `code-mode` | [CodeMode 工具](../src/pydantic_ai_harness/pydantic_ai_harness/code_mode/_toolset.py)：Monty 脚本与宿主工具调用 |
| `workflow` | [DynamicWorkflow 工具](../src/pydantic_ai_harness/pydantic_ai_harness/dynamic_workflow/_toolset.py)：脚本调度子 Agent |
| `background` | [BackgroundTools](../src/pydantic_ai_harness/pydantic_ai_harness/background_tools/_capability.py)：后台任务、消息注入与资源清理 |

Python 调试器可以单步进入 Monty 的宿主调度和工具函数；沙箱内部的 Rust 解释器不是 Python 源码。`--offline` 固定模型决策，适合断点复现；省略时连接本地 Ollama。

进阶组件和 AskUser 学习配置在 Windows 下使用 `.venv/Scripts/python.exe`，在 WSL 下询问 WSL Python 路径。连接 Windows Ollama 时，进阶配置的接口地址也应填写上面的网关地址。
