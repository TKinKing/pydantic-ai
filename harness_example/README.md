# 本地 Harness 完整学习示例

**主入口：[main.py](main.py)。默认用本地 Ollama 逐步执行工具，串起 20 个通用 Harness 能力。**

VS Code 用 **Remote - WSL** 打开仓库，选择 **Python: Harness 完整流程 (Ollama / WSL)**，按 F5。断点顺序见 [源码调试指南](DEBUGGING.md)。

## 运行

仓库根目录的 PowerShell：

~~~powershell
.\harness_example\run_ollama.ps1
# 不请求模型，固定决策，反复调试真实工具链：
.\harness_example\run_ollama.ps1 -Mode offline
~~~

脚本使用本机已有 WSL Python，并自动获取 Windows 的 WSL 网关地址。`OLLAMA_MODEL`、`OLLAMA_BASE_URL` 可覆盖模型和接口。默认沿用 `qwen2.5-harness:14b-16k`，主代理和审阅子代理均连接本地 Ollama。

| 模式 | 命令 | 行为 |
| --- | --- | --- |
| 逐步导览，默认 | `python -m harness_example.main` | 每步缩小可用工具范围，模型生成参数，框架执行工具 |
| 自主运行 | `python -m harness_example.main --mode free` | 同一组能力，模型自行选择工具，不保证覆盖每一步 |
| 离线断点 | `python -m harness_example.main --mode offline` | FunctionModel 固定决策，真实工具、护栏、文件和存储仍实际执行 |

完整流程需要 POSIX。当前 `LocalWorkspaceBackend` 依赖 POSIX 进程组，Windows 原生 Python 会收到运行环境提示。Windows 原生可运行 [追问与恢复示例](../pydantic_harness_example/README.md) 和 [最小 Planning 示例](quickstart.py)。

## 环境

本机 WSL Python 为 `/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python`；它与 Windows `.venv` 分开。新环境请从同一份当前源码安装：

~~~bash
python3 -m venv ~/.cache/pydantic-ai-harness-learning-venv
~/.cache/pydantic-ai-harness-learning-venv/bin/python -m pip install uv
~/.cache/pydantic-ai-harness-learning-venv/bin/uv pip install \
  --python ~/.cache/pydantic-ai-harness-learning-venv/bin/python \
  -e ./pydantic_graph -e './pydantic_ai_slim[openai]' \
  -e './src/pydantic_ai_harness[skills,code-mode,dynamic-workflow]' pytest debugpy
~~~

默认模型使用原 Qwen 权重，服务上下文设置为 16384 tokens。在 Windows Ollama 中创建：

~~~powershell
ollama create qwen2.5-harness:14b-16k -f ./pydantic_harness_example/Modelfile
ollama list
~~~

WSL 中从仓库根目录运行：

~~~bash
export OLLAMA_MODEL='qwen2.5-harness:14b-16k'
# Windows Ollama + WSL NAT；Ollama 需监听 WSL 可访问的地址。
export OLLAMA_BASE_URL="http://$(ip -4 route show default | awk '{print $3}'):11434/v1"
/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python -m harness_example.main
~~~

Ollama 在 WSL 内或使用镜像网络时，可使用 `http://localhost:11434/v1`。完整流程包含多次工具请求、子代理审阅和快照续接，运行时间取决于本地推理速度。

## 文件阅读顺序

| 文件 | 观察重点 |
| --- | --- |
| [quickstart.py](quickstart.py) | Agent + Planning 的最小关系 |
| [main.py](main.py) 的 `build_agent` | 工作区、20 个能力、依赖与事件 |
| [main.py](main.py) 的 `Walkthrough` | 工具范围、执行成功后推进、提前输出重试 |
| [main.py](main.py) 的 `run_example` | 保存快照、读回历史、真正发起下一轮 run |
| [tool_descriptions.py](tool_descriptions.py) | 内置工具的中文用途，保留上游参数模式 |
| [offline_model.py](offline_model.py) | 固定模型决策，验证普通与流式执行路径 |
| [advanced.py](advanced.py) | CodeMode、DynamicWorkflow、BackgroundTools 独立实验 |

## 完整流程覆盖什么

导览串联：写计划、列目录、读资料、加载技能、追问、计算进度、Shell、长工具输出、子代理、写/读/搜记忆、搜对话、写报告、完成计划、读计划。

导览只是教学控制器：每次请求末尾明确提示当前步骤，模型仍生成工具参数，工具仍由 Agent 校验和执行。教学提示只用于当前请求，不累积进持久历史。过早输出最终答案会进入重试；工具成功后才能推进。自由模式取消步骤限制。

| 能力组 | Harness 组件 | 可观察行为 |
| --- | --- | --- |
| 工作区操作 | FileSystem、Shell | 读 lesson.txt、执行 echo、写 report.md |
| 工作区知识 | RepoContext、Skills | AGENTS.md 注入、study-notes 按需加载 |
| 计划和长期知识 | Planning、Memory | SQLite 计划和文件记忆，读回、搜索 |
| 人机与委派 | AskUser、SubAgents | 明确标记的模拟偏好回答、本地模型审阅子代理 |
| 控制 | InputGuardrail、ToolGuardrail、OutputGuardrail | 输入校验、写入目标约束、最终答案重试 |
| 历史控制 | ClampOversizedMessages、ClearToolResults、SlidingWindowCompaction | 单片段限长、旧结果清理、消息窗口裁剪 |
| 结果与预算 | ToolOutputLimits、WarnNearLimits、ReportContextUsage | 长结果截断、预算提醒、上下文事件 |
| 状态与续接 | StepPersistence、ConversationSearch | 快照落盘、搜索历史、从快照发起后续 run |
| 周期指令 | SystemReminders | 到达间隔后为本次请求加入提醒 |

共 20 个通用 Harness 能力。LocalWorkspace、PrepareTools、Hooks、Agent、Model、RunContext、UsageLimits 属于核心；存储对象不重复计数。

能力挂载、工具成功执行、阈值策略触发是三个不同事实。短流程可能不会触发单消息限长或预算警告；可以改阈值并在相应钩子处观察。`coverage.json` 记录实际工具步骤，不代表全部能力的所有分支都已执行。

综合流程的 AskUser 使用明确标记的模拟回答，方便不等待输入地重复调试。真实终端追问、`DeferredToolRequests`、同一 conversation 暂停恢复在 [交互示例](../pydantic_harness_example/main.py) 中运行。

`continue_run` 读回消息历史，应用再发起后续 run。它不恢复 Python 调用栈，不回滚文件，也不会自动重建所有业务状态；示例显式保留依赖并复用存储。

## 运行产物

产物位于 `harness_example/output/demo/`，已忽略，不提交 Git。重复运行复用记忆和快照，覆盖本次报告和导出文件。

| 产物 | 内容 |
| --- | --- |
| `report.md` | 模型通过 FileSystem 写出的总结 |
| `messages.json`、`continued_messages.json` | 原运行与快照续接后的实际消息 |
| `tools.json` | 模型可见的中文工具说明与 JSON Schema |
| `coverage.json` | 本次导览实际执行记录，不是 Python 代码覆盖率 |
| `plan.db`、`memory/` | 计划与长期笔记 |
| `steps/` | 步骤事件、消息快照与工具副作用记录 |
| `skills/study-notes/SKILL.md` | 按需加载的技能正文 |

## 进阶组件

改变调用方式的能力分成三个独立实验，避免一个大组合遮蔽源码路径：

~~~bash
python -m harness_example.advanced --lesson code-mode
python -m harness_example.advanced --lesson workflow
python -m harness_example.advanced --lesson background
# 固定决策，实际执行组件：
python -m harness_example.advanced --lesson code-mode --offline
~~~

CodeMode 演示模型生成的 Python 经 Monty 调用工具；DynamicWorkflow 演示脚本调用子 Agent；BackgroundTools 演示任务提交、独立工作、结果注入。VS Code 的 **Harness 进阶组件** 配置可选择实验。

Coder 的组合继续看 [coder 预设](../pydantic_harness_example/README.md) 与 [Coder 源码](../src/pydantic_ai_harness/pydantic_ai_harness/coder/_capability.py)。云搜索、SaaS、云沙箱、计费和耐久引擎需要各自的服务环境，不在本地流程中伪造。完整能力列表见 [Harness 总览](../docs/harness/index.md)，构造参数见 [参数索引](../pydantic_harness_example/PARAMETERS.md)。模型审阅和缓存统计等专题可按对应文档继续学习。

## 验证

在安装了源码依赖的 WSL Python 环境运行：

~~~bash
python -m pytest harness_example/test_walkthrough.py harness_example/test_advanced.py -q -p no:cacheprovider
python -m pytest pydantic_harness_example/test_harness.py -q -p no:cacheprovider
~~~

测试使用 FunctionModel，在进程内经过真实 Agent、工具与存储。本地 Ollama 实跑用于验证该模型与工具协议的实际配合。
