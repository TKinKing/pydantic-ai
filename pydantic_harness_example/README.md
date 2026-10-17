# 本地 Ollama Harness 示例

要调试包含文件、Shell、计划、技能、记忆、子代理和持久化的完整流程，请先看 [综合示例](../harness_example/README.md) 和 [源码断点指南](../harness_example/DEBUGGING.md)。本目录保留 Windows 原生可运行的追问与恢复示例。

在仓库根目录运行：

~~~powershell
.\.venv\Scripts\python.exe -m pydantic_harness_example.main
~~~

在终端运行上面的命令，输入问题和回答。组合与压缩策略通过下方命令行参数选择，模型和地址通过环境变量设置。需要直接 F5 调试完整流程时，选择 **Debug Harness**，入口说明见 [综合示例](../harness_example/README.md)。

本例沿用 [核心 Agent 示例](../pydantic_agent_example/main.py) 的本地模型、学习者依赖和生命周期日志，使用 Harness 自带的 **AskUser** 替换手写追问工具。当前没有统一的 `Harness(...)` 类；能力通过 `Agent(capabilities=[...])` 组合。

## 已有示例与参数索引

仓库已有 [coding_agent.py](../src/pydantic_ai_harness/examples/coding_agent.py) 和 [research_agent.py](../src/pydantic_ai_harness/examples/research_agent.py)，默认使用云模型。本例补充本地 Ollama、追问与恢复、Windows/WSL 运行命令，并展开所用能力的构造参数。

[PARAMETERS.md](PARAMETERS.md) 列出当前版本顶层导出的全部 57 个能力构造器及辅助对象的参数、类型和默认值，包括需要外部服务的能力。它是参数索引；运行预设覆盖下表的组合，不会同时启动全部能力。

## 组合选择

| 组合 | 能力 | 运行环境 |
| --- | --- | --- |
| `learning`（默认） | 生命周期日志 + `AskUser` + 普通概念工具 | Windows、WSL、Linux |
| `context` | `learning` + `Planning`、`Memory`、`StepPersistence`、`SystemReminders`、`WarnNearLimits`，再选择一种压缩策略 | Windows、WSL、Linux |
| `coder` | `learning` + `LocalWorkspace` + `Coder` 内置能力 | WSL/Linux |

~~~powershell
# 保留最近消息
.\.venv\Scripts\python.exe -m pydantic_harness_example.main --profile context --compaction sliding

# 清理旧工具结果，保留原问题及追问结果
.\.venv\Scripts\python.exe -m pydantic_harness_example.main --profile context --compaction clear

# 预填问题和回答，便于重复观察执行过程
.\.venv\Scripts\python.exe -m pydantic_harness_example.main --profile context --question "Harness 怎么组合能力？" --answer "我想看执行顺序。"
~~~

`--answer` 为每个追问提供同一条自定义回答，交互运行时省略。终端显示选项后，输入选项文字或自己的回答，不把数字解释为选项序号。

`--compaction` 只影响 `context`，`--workspace` 只影响 `coder`。工具数量较多的组合可能需要更多模型请求或重试。能力已注册不代表模型每次都会调用它的工具；可以用“请先写计划”“请记录这条学习偏好”观察 Planning 和 Memory，压缩在历史超过阈值时触发。

## 本地模型上下文

默认模型别名 `qwen2.5-harness:14b-16k` 使用原例的 Qwen 权重，增加 `num_ctx=16384`，不重新下载权重。创建配置见下方。原模型实测只分配 4096 tokens，完整组合曾输出混乱的工具标记；因此本例提供独立的 16K 配置。它不修改原例的模型。

OpenAI 兼容接口不能直接设置上下文大小，需要 [Ollama Modelfile](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size)。本机已创建该别名；新机器运行下面的 `ollama create`。较大上下文增加内存需求；切换其他模型时，用 `ollama ps` 核实实际 CONTEXT。

## 环境准备

当前 Windows 虚拟环境在根目录的 `.venv`。新环境可安装当前源码的最小依赖：

~~~powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ./pydantic_graph -e "./pydantic_ai_slim[openai]" -e ./src/pydantic_ai_harness
uv pip install --python .venv/Scripts/python.exe pytest debugpy
~~~

需要启动 Ollama 并下载支持工具调用的模型：

~~~powershell
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama create qwen2.5-harness:14b-16k -f ./pydantic_harness_example/Modelfile
ollama list
~~~

| 配置 | 默认值 | 修改位置 |
| --- | --- | --- |
| 模型 | `qwen2.5-harness:14b-16k` | `OLLAMA_MODEL` 环境变量 |
| 地址 | `http://localhost:11434/v1` | `OLLAMA_BASE_URL` 环境变量 |
| 温度 | `0.2` | `ExampleConfig.temperature` |
| 单次输出 token 上限 | `1024` | `ExampleConfig.max_tokens` |
| 累计模型请求上限 | `16` | `ExampleConfig.request_limit` |
| 累计成功工具调用上限 | `24` | `ExampleConfig.tool_calls_limit` |
| Coder 工作目录 | `.cache/harness-example/workspace` | `--workspace` |
| 压缩触发阈值 | `24` 条消息 | `build_capabilities()` |
| 滑动窗口保留 | `16` 条，另保留首个用户问题 | `SlidingWindowCompaction` |
| 旧工具结果保留 | 最近 `4` 对，概念和追问工具除外 | `ClearToolResults` |

~~~powershell
$env:OLLAMA_MODEL = 'qwen2.5-coder:14b'
$env:OLLAMA_BASE_URL = 'http://localhost:11434/v1'
.\.venv\Scripts\python.exe -m pydantic_harness_example.main
~~~

`build_capabilities()` 展开每个已用能力的全部构造参数，包括继承的 `id`、`description`、`defer_loading`，可以逐项修改后重新运行命令对照。全包参数见 [参数索引](PARAMETERS.md)。

## 源码观察点

本目录示例从仓库根目录用 `python -m pydantic_harness_example.main` 运行，终端接受 `input()` 回答。下面列出追问和恢复流程的关键位置。

仓库的 [launch.json](../.vscode/launch.json) 只保留 **Debug Harness** 和 **Debug Agent**，分别启动综合 Harness 示例与基础 Agent 示例；本目录通过命令行运行。直接 F5 的源码单步说明见 [综合示例调试指南](../harness_example/DEBUGGING.md)。

| 断点位置 | 观察内容 |
| --- | --- |
| `build_capabilities()` | 各能力的参数及组合顺序 |
| `LearningFlow.get_instructions()` / `get_model_settings()` | 按 deps 状态提供当前步骤的指令与工具范围 |
| `build_agent()` 注册工具后 | 普通工具和能力提供的工具一起进入 Agent |
| 原例的 `LearningCapability.wrap_run()` | capability 包住整次 run |
| `explain_concept()` | 模型提出调用后框架执行 Python 函数 |
| `AskUserToolset.ask_user_question()` 的 `raise CallDeferred` | 内置能力返回延迟请求 |
| `AskUserRequest.from_tool_call(call)` | 结构化问题、选项、调用 ID |
| `ask_user_result(request, response)` | 宿主校验回答，产生工具返回值；它不是模型工具 |
| `requests.build_results(calls=calls)` | 回答与原 `tool_call_id` 关联 |
| 第二次 `agent.run()` | 相同 conversation、新的 run、累计用量 |
| `validate_answer()` | 模型漏掉概念查询或追问时请求重试 |

`AskUserToolset` 位于 `src/pydantic_ai_harness/pydantic_ai_harness/ask_user/_toolset.py`。

## 暂停、状态与组合限制

1. `AskUser(answerer=None)` 交还延迟请求，不能同时设置非空 `timeout`。应用在 run 返回后读取终端，再用 `ask_user_result` 和 `requests.build_results` 回填。
2. 恢复使用的 `conversation` 携带历史、累计用量和对话 ID；`LearningDeps` 由应用保留并再次传入。
3. `context` 显式创建 `InMemoryPlanStore`，让计划跨暂停/恢复保留。`Planning(store=None)` 默认每个 run 新建计划。
4. `LearningFlow.get_model_settings()` 返回按步骤计算的配置：先用 `ToolOrOutput(['explain_concept'])`，再用 `ToolOrOutput(['ask_user_question'])`，收到回答后恢复 `auto`。这会缩小发送给模型的工具列表，同时允许文本输出；输出校验仍要求实际完成概念工具和追问。模型而非宿主决定调用参数。规划、记忆及 Coder 工具在收到回答后开放。
5. 记忆、计划和步骤快照都放在内存，退出进程后丢失。步骤快照不等于自动恢复 Python 调用栈。磁盘存储与持久执行见各能力文档。
6. 两种压缩策略单选。本例使用消息数阈值；配置 token 比例前要核实 Ollama 实际 `num_ctx`，不能把模型最大窗口当作服务正在使用的窗口。本例没有用 `fallback_context_window` 推断 Qwen 的实际窗口。
7. `cache_ttl` 是缓存提示，不表示 Ollama 具备对应云端缓存服务。
8. `Coder` 自带文件、Shell、仓库上下文、压缩和输出限制，不再叠加 `context`。`sub_agents=False` 关闭委派；改为 `True` 可观察 `delegate_task`，其模型继承父 Agent。`Coder(workspace=...)` 已弃用且忽略，目录由 `LocalWorkspace` 设置。

## Coder：WSL/Linux 运行

`LocalWorkspaceBackend` 在 Windows 原生 Python 下实际报错：

~~~text
NotImplementedError: `LocalWorkspaceBackend` only supports POSIX platforms at the moment
~~~

因此 `coder` 使用 WSL/Linux。它可以读写工作区、执行 Shell；默认创建独立示例目录，目录隔离不是操作系统沙箱。

本机已有 WSL 解释器 `/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python`，与 Windows `.venv` 分开。在 WSL 中进入仓库：

~~~bash
cd /mnt/d/tk/newpc1/app/pydantic-ai
export OLLAMA_MODEL='qwen2.5-harness:14b-16k'
# Ollama 在 Windows 上，且 WSL 使用 NAT 网络：
export OLLAMA_BASE_URL="http://$(ip -4 route show default | awk '{print $3}'):11434/v1"
/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python -m pydantic_harness_example.main --profile coder
~~~

Windows Ollama 的监听地址及防火墙需允许 WSL 访问。若 Ollama 运行在 WSL 内，或镜像网络可用，地址可以是 `http://localhost:11434/v1`。

在 VS Code 中运行时，可安装 **WSL** 扩展并选择“在 WSL 中重新打开文件夹”，再在其终端执行上面的命令。Coder 没有独立的 F5 配置；解释器和 Ollama 地址使用命令中的设置。

## 不连接模型的验证

~~~powershell
.\.venv\Scripts\python.exe -m pytest pydantic_harness_example/test_harness.py -q -p no:cacheprovider
~~~

测试使用 `FunctionModel`，实际经过 Agent、Harness 工具、暂停/恢复，并调用规划和记忆工具验证跨 run 存储。Coder 的 POSIX 测试在 Windows 跳过，Windows 另测平台提示。

~~~bash
/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python -m pytest pydantic_harness_example/test_harness.py -q -p no:cacheprovider
~~~
