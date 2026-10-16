# Pydantic AI 核心 Agent 交互示例

[main.py](main.py) 使用 Pydantic AI 核心 API 和本地 Ollama，演示一次可交互的问答：用户提出问题，LLM 调用延迟工具向用户追问，应用把用户回答交回给 Agent，LLM 再输出最终答案。

在仓库根目录的 PowerShell 运行（与 VS Code 调试使用同一个虚拟环境）：

```powershell
.\.venv\Scripts\python.exe -u .\pydantic_agent_example\main.py
```

默认模型是 `qwen2.5:14b-instruct-q4_K_M`，默认接口为 `http://localhost:11434/v1`。需要启动 Ollama，并在上述虚拟环境中安装当前仓库的 `pydantic-ai-slim[openai]`。设置 `OLLAMA_MODEL` 和 `OLLAMA_BASE_URL` 可切换模型与地址；模型须支持工具调用。

已有的 `run_ollama.ps1` 是 WSL 启动入口，使用 `/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python`；它与 F5 使用的 Windows 虚拟环境不同。

需要使用现成 Harness 能力（AskUser、Planning、Memory、Coder）时，见 [Harness 本地模型与调试示例](../pydantic_harness_example/README.md)。

## VS Code 断点调试

用 VS Code 打开仓库根目录，安装 Microsoft 的 Python 和 Python Debugger 扩展。在“运行和调试”中选择 **Python: Pydantic AI 学习示例 (Ollama)**，设置断点后按 **F5**。启动时输入模型名称和接口地址，默认值可直接按回车确认。

配置位于 [.vscode/launch.json](../.vscode/launch.json)。`integratedTerminal` 支持交互输入；在底部终端回答问题，调试控制台不接受这里的 `input()`。`justMyCode: false` 允许单步进入框架源码。

可按以下顺序设置断点：

| 断点 | 观察内容 | 继续跟进的源码 |
| --- | --- | --- |
| `build_agent()` 最后的工具注册 | Python 函数如何注册为模型可调用的工具 | `agent.tool()` / `agent.tool_plain()` |
| `LearningCapability.wrap_run()` 的 `await handler()` | wrap 的前后半段如何包住一次运行 | `agent/__init__.py` 的 `_run_lifecycle_hooks()` |
| `explain_concept()` | 模型传入的 `concept` 和应用提供的 `ctx.deps` | `tool_manager.py`、`toolsets/function.py` |
| `ask_learner()` 的 `raise CallDeferred` | 用异常通知框架交出工具调用 | `_tool_execution.py` 的延迟工具处理 |
| `run_interactive()` 的 `while` | `result.output.calls` 中的参数和 `tool_call_id` | `DeferredToolRequests` |
| `requests.build_results(calls=answers)` | 用户回答怎样与工具调用 ID 对应 | `_deferred.py` |
| 第二次 `agent.run()` | `conversation.messages` 和 `deferred_results` | `_agent_graph.py` 的 `UserPromptNode._handle_deferred_tool_results()` |
| `validate_answer()` 与最后的打印 | 最终输出校验、`all_messages()` 与 `new_messages()` | 输出处理和 `AgentRunResult` |

上表框架文件位于 `pydantic_ai_slim/pydantic_ai/`。暂停后恢复是一个新的 run，所以 `wrap_run`、`before_run`、`after_run` 会再次出现；`run_id` 改变，`conversation_id` 保持一致。

## 交互流程

1. `run_interactive()` 读取用户最初的问题并调用 `agent.run()`，例如输入“Agent 是怎么调用工具的？”。
2. `explain_concept()` 是普通的上下文工具：Agent 在本次运行内调用它，应用函数返回结果。
3. `ask_learner()` 抛出 `CallDeferred`，Agent 返回 `DeferredToolRequests`，而不是继续生成最终答案。
4. 应用用 `call.args_as_dict()` 读取 LLM 提出的问题，兼容 JSON 字符串和字典参数。用户在终端回答，例如“我熟悉 JS，想看 Python 函数到底什么时候执行”。应用用 `requests.build_results()` 创建 `DeferredToolResults`，其中 `calls` 的 key 是 `tool_call_id`。
5. 应用把原来的 `conversation` 和延迟工具结果传给下一次 `agent.run()`；LLM 收到用户回答后生成最终答案。
6. `validate_answer()` 确认普通工具已执行且用户已回答。若模型漏掉步骤便直接输出文本，抛出 `ModelRetry` 请模型补齐流程；反复失败仍会达到重试或用量上限。

`ask_learner()` 中没有 `input()`：它只抛出延迟信号。终端输入发生在第一次 `agent.run()` 返回之后，用户的回答作为这个工具的返回值交给模型，恢复时不会重新调用原工具函数来取得回答。这里的“延迟”指延迟完成工具调用；工具定义从一开始就对模型可见。

`conversation` 携带历史、累计用量和对话 ID，恢复时不再同时传 `message_history`、`usage` 或 `conversation_id`。同一实例的 `deps` 也继续传入，但它是应用自己的状态，不会自动保存到 conversation。每次启动本例创建新的 `LearningDeps`。

最终显示整个对话的累计模型请求数，以及成功返回的工具调用数。本例普通工具返回结果会计入 `usage.tool_calls`，抛出 `CallDeferred` 和外部填回延迟结果不计入此数值。`UsageLimits` 约束暂停前后累计的用量。按 Ctrl+C 可退出。

## 组件对照

| 组件 | 示例位置与作用 |
| --- | --- |
| 依赖注入 | `LearningDeps` 由 `deps=` 传入；普通工具通过 `RunContext` 读取 |
| 普通工具 | `explain_concept` 在当前 Agent 运行中执行并返回结果 |
| 延迟工具 | `ask_learner` 抛出 `CallDeferred`，由应用收集用户输入并在恢复时返回结果 |
| 暂停与恢复 | `DeferredToolRequests`、`requests.build_results()` 和 `conversation` |
| capability / cap | `LearningCapability` 的 `wrap_run`、`before_run`、`before_model_request`、`after_run` |
| 输出校验 | `validate_answer` 用 `ModelRetry` 要求模型补齐工具和追问步骤 |
| 本地模型 | `OpenAIChatModel` + `OllamaProvider` |

工具由模型选择调用；capability 钩子由框架调用。终端中的 `[tool]`、`[deferred tool]`、`[cap.*]` 和 `[应用]` 日志分别标出普通工具、延迟工具、生命周期和暂停/恢复的位置。

## 不连接模型的流程验证

```powershell
.\.venv\Scripts\python.exe -m pytest pydantic_agent_example/test_main.py -q -p no:cacheprovider
```

这两个用例使用 `FunctionModel` 控制模型响应，实际经过 Agent、普通工具、延迟工具和恢复流程，分别覆盖字典与 JSON 字符串参数。F5 默认仍使用真实 Ollama 模型。
