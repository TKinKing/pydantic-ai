# Pydantic AI 核心 Agent 中文示例

[main.py](main.py) 只使用 Pydantic AI 核心 API，通过本地 Ollama 运行。它与 [Harness 综合示例](../harness_example/README.md) 采用相同的中文注释风格，便于比较核心 Agent 与可选 Harness 能力。

在仓库根目录的 PowerShell 运行一次，代码会按固定顺序展示五种运行入口：

```powershell
.\pydantic_agent_example\run_ollama.ps1
```

默认模型是本机已安装的 `qwen2.5:14b-instruct-q4_K_M`。主脚本也可在 Linux/macOS 直接运行；设置 `OLLAMA_MODEL` 和 `OLLAMA_BASE_URL` 可切换模型与地址。需要安装当前仓库的 `pydantic-ai-slim[openai]`，Windows 启动脚本沿用 Harness 示例的 WSL 学习环境。

## VS Code 断点调试

用 VS Code 打开仓库根目录，安装 Microsoft 的 Python 和 Python Debugger 扩展。在“运行和调试”中选择 **Python: Pydantic AI 学习示例 (Ollama)**，设置断点后按 **F5**。启动时输入模型名称和接口地址，默认值可直接按回车确认。

配置位于 [launch.json](../.vscode/launch.json)，Windows 使用仓库的 `.venv/Scripts/python.exe`，Linux/macOS 使用 `.venv/bin/python`。此入口直接运行 Python，需在该虚拟环境中安装当前仓库及 OpenAI 依赖，并启动 Ollama；它不使用 PowerShell 脚本中的 WSL 虚拟环境。在 VS Code Remote WSL 中调试时，可把配置的 `python` 改成已准备好的 `/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python`，接口地址填写 Windows 主机地址。

建议在 `LearningCapability.before_model_request`、`explain_concept`、`learning_progress` 和 `validate_note` 中设置断点，分别观察请求上下文、模型传入的工具参数、`ctx.deps` 和最终输出。配置的 `justMyCode: false` 允许单步进入 Pydantic AI 源码。F5 会执行整个示例的五种运行入口。

## 阅读顺序

1. `LearningDeps` 与 `StudyNote`：应用传入的依赖和经过 Pydantic 校验的最终答案。
2. `LearningCapability`：通过 `before_run` 和 `before_model_request` 观察运行生命周期。
3. `build_agent()`：配置模型、静态与动态指令、两种工具、toolset、capabilities、`ToolOutput` 和输出校验器。
3. `run_sync()`：第一个执行的独立同步示例，要求三个工具真实执行并校验最终输出。可在 `agent.run_sync(...)` 和下一行打断点，观察调用前后的状态；它在文件末尾先于 `asyncio.run(main())` 执行，因为不能在已有事件循环中调用。
4. `run_normal()`：使用 `run()`、`UsageLimits`、`all_messages()` 和 `new_messages()` 继续对话；校验两种工具确实执行，并计算 `1/2`。
5. `run_stream()`、`run_events()`、`run_steps()`：依次展示结构化流式输出、事件流和节点遍历。

每种运行方式都会发送新的本地模型请求；一次完整执行会运行全部五种方式，因此会有多次模型推理。模型可能选择不同工具调用顺序；`run()` 部分要求真实工具返回，其他部分专门观察运行接口。`run_stream()` 收到首次最终输出后就结束，不适合用这个入口强制模型先完成其他工具调用；需要观察完整工具流程时使用 `run_stream_events()` 或 `iter()`。`ModelRetry` 可要求模型修正工具参数或最终答案，但流式输出已经开始后无法重试。

单个示例无法覆盖 Pydantic AI 所有专用 API；这里覆盖日常构建 Agent 最常用的部分。更多内容见仓库中的 [Agent 文档](../docs/agent.md)、[工具文档](../docs/tools.md)、[输出文档](../docs/output.md)和[消息历史文档](../docs/message-history.md)。

## 常用组件在哪里

| 组件 | 示例位置与作用 |
| --- | --- |
| 模型与 Provider | `OpenAIChatModel` + `OllamaProvider`，连接本地模型 |
| Agent 配置 | `name`、`model_settings`、`retries`，配置名称、采样与重试 |
| 依赖注入 | `deps_type=LearningDeps` 声明类型，`deps=` 传实例，`ctx.deps` 读取 |
| 静态与动态指令 | `instructions=` 与 `agent.instructions(...)`，提供任务和学习者信息 |
| 普通工具 | `agent.tool_plain(...)` 注册 `explain_concept`，参数由模型填写 |
| 带上下文工具 | `agent.tool(...)` 注册 `learning_progress`，应用提供 `RunContext` |
| 工具集合 | `FunctionToolset` 注册 `study_checklist`，通过 `toolsets=` 接入 Agent |
| capabilities / caps | `capabilities=[LearningCapability()]`，框架在生命周期节点调用钩子 |
| 结构化输出 | `ToolOutput(StudyNote)` + Pydantic 字段校验 |
| 业务校验与重试 | `agent.output_validator(...)` + `ModelRetry`，要求模型修正答案或工具参数 |
| 预算与用量 | `UsageLimits` 限制请求与工具调用，`result.usage` 查看用量 |
| 消息历史 | `message_history`、`all_messages()`、`new_messages()`，延续对话 |
| 运行入口 | `run_sync`、`run`、`run_stream`、`run_stream_events`、`iter` |

工具由模型选择调用；capability 钩子由框架调用。终端中的 `[tool_plain]`、`[tool]`、`[toolset]` 和 `[capability]` 会显示实际执行位置。普通运行的输出校验器要求三个工具均已成功返回，避免只注册工具却没有执行。

流式演示不强制先完成工具调用；capability 仍然执行。MCP、内置搜索、多模态、延迟工具审批和持久化执行需要额外环境或专用业务场景，本示例不把它们放入默认运行链路。
