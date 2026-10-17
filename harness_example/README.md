# Harness 完整学习示例

**主入口：[main.py](main.py)。有 DeepSeek API Key 时调用 DeepSeek，否则使用本地 Ollama。依次执行 18 步工具流程、跨会话记忆、万条历史滑窗和增量摘要。**

直接调试：在本机 VS Code 打开仓库，在“运行和调试”中选择第一项 **Python: Harness 直接启动 (F5 / Local)**，按 F5。它使用仓库的 `.venv`，自动启动完整例子并暂停在入口，不需要 WSL 或先运行 `just`。断点顺序见 [源码调试指南](DEBUGGING.md)。

## 模型选择

为让各专题独立运行，模型配置集中在 [model_config.py](model_config.py)。其中 `DEEPSEEK_API_KEY` 变量控制选择，默认读取同名环境变量：

~~~python
DEEPSEEK_API_KEY = getenv('DEEPSEEK_API_KEY', '')
~~~

有非空值时，主代理和 reviewer 都使用 DeepSeek；空字符串或只有空白时，都使用原本的本地 Ollama。入口不增加命令行参数。Key 无效或请求失败会直接报错，不自动切回本地模型。

F5 和 `just` 会读取仓库根目录的 `.env`，可在其中设置 `DEEPSEEK_API_KEY=你的密钥`、`OLLAMA_MODEL` 或 `OLLAMA_BASE_URL`。直接运行 PowerShell 脚本或 Python 时使用当前环境变量，不会自动加载 `.env`。

DeepSeek 使用仓库已支持的 `deepseek-v4-flash` 别名，并关闭深度思考以观察工具调用。[官方说明](https://api-docs.deepseek.com/)确认该别名仍被接受；上下文报告按[官方模型规格](https://api-docs.deepseek.com/quick_start/pricing/)的 1M 计算，本地模型按 16K 计算。

## 运行

在仓库根目录、已安装 `just` 的终端执行：

~~~powershell
just harness-test   # 运行本目录全部测试，不需要启动 Ollama 或提供真实 API Key
just harness        # 执行完整例子，按 Key 选择 DeepSeek 或本地 Ollama
just harness-debug  # 启动 debugpy，等待 VS Code 附加后才执行例子
~~~

三条命令都使用当前机器的 Python：Windows 为 `.venv/Scripts/python.exe`，Linux/macOS 为 `.venv/bin/python`。`HARNESS_PYTHON` 环境变量可为 just 命令指定其他本地解释器。

VS Code 的 **终端 → 运行任务** 也提供 `just harness`、`just harness-test`。完整例子不打印运行日志；断点中检查变量，运行后的消息、报告和历史窗口保存在 `output/`。测试结果仍由 pytest 输出。

`just harness-debug` 会等待调试器连接。随后选择 **Python: Harness 附加 just 调试 (Local)** 并按 F5；完整步骤见 [调试指南](DEBUGGING.md)。直接 F5 启动使用第一项 **Python: Harness 直接启动 (F5 / Local)**。

也可以在仓库根目录直接运行原来的 PowerShell 脚本：

~~~powershell
.\harness_example\run_ollama.ps1
~~~

脚本使用本机 `.venv`，本地模型默认 `qwen2.5-harness:14b-16k`，接口默认 `http://localhost:11434/v1`。也可以直接执行 `.\.venv\Scripts\python.exe -m harness_example.main`。

入口不读取命令行参数。直接运行 `python -m harness_example.main`，每步缩小可用工具范围，由所选模型生成参数、框架执行工具，完成后从快照续接。工作区固定为 `harness_example/output/demo/`。

随后执行独立的记忆与历史专题，产物放在 `harness_example/output/memory-history/`。MCP 服务由客户端自动启动和关闭，不需要先开一个服务终端。

之前需要 WSL，是因为内置 `LocalWorkspaceBackend` 的进程组清理和 Harness `Shell` 的命令包装使用 POSIX 接口。现在 Windows 通过独立的 [local_workspace.py](local_workspace.py) 适配本地文件和受限 `echo` 工具，其他 Harness 能力仍走原来的源码。Linux/macOS 继续使用内置后端。这是示例的适配层，没有修改库的 Windows 支持范围。

## 环境

本机 `.venv` 已安装所需依赖。新 Windows 环境可在仓库根目录安装：

~~~powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ./pydantic_graph -e './pydantic_ai_slim[openai,mcp]' -e './src/pydantic_ai_harness[skills,code-mode,dynamic-workflow]' pytest debugpy
~~~

Linux/macOS 使用同样的源码依赖，将解释器路径改为 `.venv/bin/python`。

默认模型使用原 Qwen 权重，服务上下文设置为 16384 tokens。在 Windows Ollama 中创建：

~~~powershell
ollama create qwen2.5-harness:14b-16k -f ./pydantic_harness_example/Modelfile
ollama list
~~~

Ollama 和 Python 都在当前机器运行，默认地址为 `http://localhost:11434/v1`。完整流程包含多次工具请求、子代理审阅和快照续接，运行时间取决于本地推理速度。

## 六个概念怎样落到代码

### 1. Workspace：工具使用的工作环境

`create_local_workspace(workspace)` 选择当前系统的后端。Windows 的 `NativeWorkspace` 将模型侧 `/workspace` 路径映射到真实目录；Linux/macOS 使用内置 `LocalWorkspace`。文件工具、Skills、FileStore 仍统一访问 `ctx.workspace`。工作区常用于 coding agent，也可用于分析资料、生成报告；它不是操作系统级沙箱。

Windows 的 `NativeShell` 只演示 `run_command("echo harness-demo")` 一类简单命令，真实调用 `cmd.exe`，不支持任意脚本或 POSIX 后台 Shell。它通过能力接口提供工具，便于观察如何替换平台相关实现。文件记忆使用 FileStore 的纯文件后端路径，不执行 `mv` 等 Unix 命令。

Harness 不要求每个 Agent 都有工作区。本例因为组合了 FileSystem、Shell、RepoContext、Skills 和文件记忆才使用它；独立的 [RAG](rag.py) 和 [MCP 客户端](mcp_client.py) 没有挂 `LocalWorkspace`。换成数据库记忆、HTTP 检索和远程工具，也可以完全不接触本地文件。

### 2. Skills：先展示目录，按需加载正文

`prepare_workspace()` 创建 `skills/study-notes/SKILL.md`，包含 `name`、`description` 和中文学习步骤。`Skills('skills')` 发现技能，模型先看到名字和简介，随后实际调用 `load_capability(id='study-notes')`，正文才作为能力指令进入后续请求。技能文件里的附带脚本不会因此自动执行。

断点从 `prepare_workspace`、教学中的 `load_capability` 开始，再进入 Harness `skills/_loader.py`、`skills/_capability.py` 和核心的延迟能力加载逻辑。

### 3. Memory：用户可以跨 conversation 共用笔记

主流程明确使用 `namespace=lambda ctx: ctx.deps.user_id`，身份由应用提供。`conversation_id` 标识一次对话，`user_id` 标识这个用户的长期记忆空间，二者不能混用。

[demonstrate_memory](memory_history.py) 做两个真实运行：第一个 Agent 调用 `write_memory` 写入学习偏好；随后创建全新的 Agent，不传旧 `message_history` 或 `conversation_id`，但使用相同文件后端和用户 namespace。第二个 Agent 从 Memory 注入的笔记里回答偏好。测试还检查另一个用户看不到该笔记。

观察 `memory_new_conversation_request.json`，就能看到新对话实际接收了什么。Memory 保存的是明确写入的笔记，不会自动把全部聊天历史变成长期记忆。

### 4. History：完整档案与模型本次可见窗口分开

应用通过 `agent.run(message_history=...)` 提供历史。[load_history](memory_history.py) 演示从 JSON 档案读取并校验统一消息类型；真实系统可以在这一层换成数据库查询。

`demonstrate_history()` 分别展示：

| 路径 | 实际做的事 | 要观察的文件 |
| --- | --- | --- |
| 完整档案 | 生成、保存、再读回 10000 条合成消息 | `full_history.json` |
| 滑窗裁剪 | `SlidingWindowCompaction` 在请求模型前裁到约 20 条；不调用总结模型 | `sliding_request.json` |
| 增量语义摘要 | `SummarizingCompaction` + `compact_now` 两次处理 60 条新消息，第二次更新上一份摘要 | `summary_window.json`、`summary_request.json` |

摘要示范只覆盖前 **120 条**，不宣称总结了全部一万条。它真实调用模型，可能损失细节；滑窗则直接移除旧消息。本例特意关闭滑窗的“保留首条用户消息”，便于观察最早的课程代号怎样消失。

生产中通常在历史增长时持续更新摘要，提供“系统指令 + 长期记忆 + 累积摘要 + 最近消息 + 本次检索结果”。一次导入一万条旧历史时，要按模型 token 预算分批补建摘要，不能只按消息条数判断能否放进上下文。本例的小批次是短文本教学数据，不是通用 token 上限算法。

完整档案保持独立，不用裁剪后的列表覆盖它。主流程的 `ConversationSearch(SnapshotHistorySource(store))` 还展示了按需搜索已保存的历史；它与 Memory 笔记、外部知识库是不同的数据来源。

### 5. RAG：把已有检索系统作为依赖接进来

[rag.py](rag.py) 的核心链路是 `KnowledgeRAG` → `search_knowledge` → `ctx.deps.retrieval.search()` → 带 `source` 的证据 → 模型回答。能力提供工具和使用指令，检索系统负责找到资料。

默认 `InMemoryRetrievalService` 只做关键词匹配，便于直接运行，不包含 embedding 或向量数据库。外界已有 RAG 时，实现 `RetrievalService.search()` 接自己的 SDK 即可。若是 HTTP 服务，`HttpRetrievalService` 使用这个示例约定：

~~~text
POST 请求：{"query": "问题", "limit": 3}
JSON 响应：{"hits": [{"title": "标题", "text": "原文片段", "source": "文档地址或ID"}]}
~~~

接入示例（把地址换成实际服务）：

~~~python
import asyncio
import httpx

from harness_example.rag import HttpRetrievalService, run_rag


async def main() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        service = HttpRetrievalService(client, 'http://localhost:8000/search')
        await run_rag('你的业务问题', retrieval=service)


asyncio.run(main())
~~~

鉴权头由调用方的 HTTP client 配置；不同 JSON 格式在适配器里转换。完整流程 `run_example(retrieval=service)` 也支持同一个服务对象。检索返回空结果时，模型应说明缺少依据。

### 6. MCP：工具的跨进程协议

[mcp_server.py](mcp_server.py) 用 SDK 的 `FastMCP` 定义两个工具：`mcp_add`、`mcp_echo`。[mcp_client.py](mcp_client.py) 用当前 Python 启动服务，通过 `StdioTransport`、`MCPToolset` 和核心 `MCP` 能力注册到 Agent；`async with agent` 管理连接生命周期。

完整流程实际调用 `mcp_add(7, 5)`，独立客户端再演示回显。MCP server 的 stdout 专供协议通信，不能随意 `print`。MCP 是连接工具的协议，RAG 是检索后生成回答的方式，二者也能组合：检索工具可以由 MCP server 提供。

可分别运行专题，不需要模式参数：

~~~bash
python -m harness_example.memory_history
python -m harness_example.rag
python -m harness_example.mcp_client
~~~

## 文件阅读顺序

| 文件 | 观察重点 |
| --- | --- |
| [quickstart.py](quickstart.py) | Agent + Planning 的最小关系 |
| [model_config.py](model_config.py) | API Key 与本地模型的统一选择 |
| [main.py](main.py) 的 `build_agent` | 工作区、能力组合、依赖与事件 |
| [local_workspace.py](local_workspace.py) | Windows 文件后端和原生命令适配；平台选择边界 |
| [main.py](main.py) 的 `Walkthrough` | 工具范围、执行成功后推进、提前输出重试 |
| [main.py](main.py) 的 `run_example` | 保存快照、读回历史、真正发起下一轮 run |
| [memory_history.py](memory_history.py) | 跨 conversation 记忆、历史加载、滑窗、增量摘要 |
| [rag.py](rag.py) | 自定义能力如何接入已有检索 API |
| [mcp_server.py](mcp_server.py)、[mcp_client.py](mcp_client.py) | 服务定义、工具发现、跨进程调用和连接生命周期 |
| [tool_descriptions.py](tool_descriptions.py) | 内置工具的中文用途，保留上游参数模式 |
| [offline_model.py](offline_model.py) | 自动化测试使用的固定模型决策，验证普通与流式执行路径 |
| [advanced.py](advanced.py) | CodeMode、DynamicWorkflow、BackgroundTools 独立实验 |

## 完整流程覆盖什么

导览串联：写计划、列目录、读资料、加载技能、检索知识、MCP 加法、追问、计算进度、Shell、长工具输出、子代理、写/读/搜记忆、搜对话、写报告、完成计划、读计划。

导览只是教学控制器：每次请求末尾明确提示当前步骤，模型仍生成工具参数，工具仍由 Agent 校验和执行。教学提示只用于当前请求，不累积进持久历史。过早输出最终答案会进入重试；工具成功后才能推进。

| 能力组 | Harness 组件 | 可观察行为 |
| --- | --- | --- |
| 工作区操作 | FileSystem、Shell / Windows NativeShell | 读 lesson.txt、执行 echo、写 report.md |
| 工作区知识 | RepoContext、Skills | AGENTS.md 注入、study-notes 按需加载 |
| 计划和长期知识 | Planning、Memory | SQLite 计划和文件记忆，读回、搜索 |
| 人机与委派 | AskUser、SubAgents | 明确标记的模拟偏好回答、与主代理共用模型配置的审阅子代理 |
| 控制 | InputGuardrail、ToolGuardrail、OutputGuardrail | 输入校验、写入目标约束、最终答案重试 |
| 历史控制 | ClampOversizedMessages、ClearToolResults、SlidingWindowCompaction | 单片段限长、旧结果清理、消息窗口裁剪 |
| 结果与预算 | ToolOutputLimits、WarnNearLimits、ReportContextUsage | 长结果截断、预算提醒、上下文事件 |
| 状态与续接 | StepPersistence、ConversationSearch | 快照落盘、搜索历史、从快照发起后续 run |
| 周期指令 | SystemReminders | 到达间隔后为本次请求加入提醒 |

POSIX 组合包含 20 个通用 Harness 能力；Windows 组合包含 19 个，并用示例的 `NativeShell` 替代内置 Shell。LocalWorkspace、PrepareTools、Hooks、Agent、Model、RunContext、UsageLimits 属于核心；存储对象不重复计数。

`KnowledgeRAG`、`NativeWorkspace`、`NativeShell` 是示例自己编写的能力，`MCP` 是核心能力，不计入内置 Harness 组件数量。历史专题另外使用 `SummarizingCompaction`。

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

推荐从仓库根目录运行 `just harness-test`。也可以在已激活本地 `.venv` 的终端分别执行：

~~~bash
python -m pytest harness_example/test_walkthrough.py harness_example/test_advanced.py -q -p no:cacheprovider
python -m pytest harness_example/test_model_selection.py -q -p no:cacheprovider
python -m pytest harness_example/test_memory_history.py harness_example/test_rag.py harness_example/test_mcp.py -q -p no:cacheprovider
python -m pytest harness_example/test_local_workspace.py -q -p no:cacheprovider
~~~

流程测试使用 FunctionModel，经过真实 Agent、工具与存储；MCP 测试启动真实 stdio 子进程，历史测试还用本机 HTTP 服务验证模型连接的生命周期。模型选择测试检查空 Key、空白 Key 和非空 Key，并在 SDK 请求发送前截停，验证模型路由和 DeepSeek 关闭思考的参数，不使用真实密钥或访问云 API。本地 Ollama 实跑用于验证该模型与工具协议的实际配合。
