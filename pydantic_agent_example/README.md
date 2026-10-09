# Pydantic AI 核心 Agent 中文示例

[main.py](main.py) 只使用 Pydantic AI 核心 API，通过本地 Ollama 运行。它与 [Harness 综合示例](../harness_example/README.md) 采用相同的中文注释风格，便于比较核心 Agent 与可选 Harness 能力。

在仓库根目录的 PowerShell 运行：

```powershell
.\pydantic_agent_example\run_ollama.ps1          # run：异步执行，并用消息历史继续对话
.\pydantic_agent_example\run_ollama.ps1 sync     # run_sync：同步调用
.\pydantic_agent_example\run_ollama.ps1 stream   # run_stream：逐次接收结构化输出
.\pydantic_agent_example\run_ollama.ps1 events   # run_stream_events：观察模型和工具事件
.\pydantic_agent_example\run_ollama.ps1 iter     # iter：逐个观察运行节点
```

默认模型是本机已安装的 `qwen2.5:14b-instruct-q4_K_M`。主脚本也可在 Linux/macOS 直接运行；设置 `OLLAMA_MODEL` 和 `OLLAMA_BASE_URL` 可切换模型与地址。需要安装当前仓库的 `pydantic-ai-slim[openai]`，Windows 启动脚本沿用 Harness 示例的 WSL 学习环境。

## 阅读顺序

1. `LearningDeps` 与 `StudyNote`：应用传入的依赖和经过 Pydantic 校验的最终答案。
2. `build_agent()`：配置模型、静态与动态指令、两种工具、`ToolOutput` 和输出校验器。
3. `run_normal()`：使用 `run()`、`UsageLimits`、`all_messages()` 和 `new_messages()` 继续对话；校验两种工具确实执行，并计算 `1/2`。
4. `run_stream()`、`run_events()`、`run_steps()`：观察同一个 Agent 的不同运行入口。
5. 文件末尾的 `run_sync()`：没有事件循环的同步程序可使用此入口。

每个运行模式会发送新的本地模型请求。模型可能选择不同工具调用顺序；默认 `run` 模式要求真实工具返回，其他模式专门观察运行接口。`run_stream()` 收到首次最终输出后就结束，不适合用这个入口强制模型先完成其他工具调用；需要观察完整工具流程时使用 `run_stream_events()` 或 `iter()`。`ModelRetry` 可要求模型修正工具参数或最终答案，但流式输出已经开始后无法重试。

单个示例无法覆盖 Pydantic AI 所有专用 API；这里覆盖日常构建 Agent 最常用的部分。更多内容见仓库中的 [Agent 文档](../docs/agent.md)、[工具文档](../docs/tools.md)、[输出文档](../docs/output.md)和[消息历史文档](../docs/message-history.md)。
