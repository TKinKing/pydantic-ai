# 中文 Harness 学习示例

先读 [quickstart.py](quickstart.py)，再读 [main.py](main.py) 的 `build_agent()`。

这个例子用“读取学习资料并写总结”串起 **20 个 Harness 能力**，覆盖大部分通用能力类别。它没有启用所有外部服务集成，也不是把 20 个能力都变成了模型可以调用的工具：有些能力通过生命周期钩子自动工作。

所有非空 Python 代码行都有中文注释，自定义工具有中文说明，启用的内置工具也有中文用途和参数说明。`PrepareTools` 翻译准备阶段可见的工具描述；核心随后生成的 `load_capability` 加载器保留上游描述，其中文对照在 `tool_descriptions.py`。内置工具的参数名、JSON Schema 约束和返回协议保持上游格式；部分内置返回文字仍为英文。不要修改工具源码来翻译它们。

## 先运行

### 当前 Windows 机器

最小示例可以直接运行，不需要 API Key：

```powershell
.\.venv\Scripts\python.exe harness_example\quickstart.py # 使用已有 Windows Python 环境运行最小示例。
```

综合示例已在本机 WSL 环境安装依赖并验证。仓库根目录的 PowerShell 中运行：

```powershell
wsl --cd D:\tk\newpc1\app\pydantic-ai -- /home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python harness_example/main.py # 在 WSL 执行综合示例。
```

这里使用 WSL 是因为当前检出的 `LocalWorkspaceBackend` 明确只支持 POSIX：它依赖进程组实现命令超时后的清理。直接用 Windows Python 运行综合示例，会收到中文提示。最小示例没有文件或命令工作区，因此没有这个限制。

### 其他 Linux、macOS 或新的 WSL 环境

在仓库根目录安装**当前源码**，让核心、图执行器与 Harness 保持一致。不要把仓库里的新 Harness 和旧版已发布核心混装。

```bash
python3 -m venv ~/.cache/pydantic-ai-harness-learning-venv # 创建独立学习环境，不替换仓库已有虚拟环境。
~/.cache/pydantic-ai-harness-learning-venv/bin/python -m pip install uv # 安装依赖管理工具。
~/.cache/pydantic-ai-harness-learning-venv/bin/uv pip install --python ~/.cache/pydantic-ai-harness-learning-venv/bin/python -e ./pydantic_graph -e ./pydantic_ai_slim -e './src/pydantic_ai_harness[skills]' # 从本地源码安装三个包及技能解析依赖。
~/.cache/pydantic-ai-harness-learning-venv/bin/python harness_example/main.py # 执行离线综合演示。
```

依赖安装需要联网。安装完成后的默认演示不调用外部模型服务，不需要密钥。

## 文件阅读顺序

| 文件 | 学什么 |
| --- | --- |
| [quickstart.py](quickstart.py) | `Agent`、`capabilities`、`Planning`、`run_sync` 的最小关系 |
| [main.py](main.py) 的 `build_agent` | 工作区、20 个能力、依赖注入、业务工具、事件订阅怎样组合 |
| [main.py](main.py) 的 `main` | 应用如何管理目录、资源生命周期、运行预算和持久化产物 |
| [tool_descriptions.py](tool_descriptions.py) | 每个内置或自定义工具的中文用途和主要参数 |
| [offline_model.py](offline_model.py) | 如何通过 `FunctionModel` 固定模型决策、验证真实工具链；普通和流式响应怎样转换 |

`offline_model.py` 是教学支架，不是生产 Agent 的业务编排方案。真实模型通常自己决定调用哪个工具、传哪些参数，以及如何根据结果继续。

## 先理解这几个区别

| 概念 | 在 Pydantic AI 中的位置 | 本例对应 |
| --- | --- | --- |
| `Agent` | 核心运行时，管理模型请求、工具执行、重试、消息历史和输出 | `build_agent()` 创建的主代理 |
| `Model` | 核心模型接口，适配供应商或本地测试函数 | `FunctionModel`、`TestModel`，或 `--model` 选择的真实模型 |
| Capability | 组合工具、指令与生命周期钩子的核心抽象 | Harness 实现的 `Memory`、`Planning` 等 |
| Tool / Toolset | 模型可调用的函数与工具集合；由核心校验参数并执行 | `read_file`、`write_plan`、`learning_progress` |
| Hook | 在运行、模型请求、工具执行等时机介入 | 输入护栏、输出限长、快照保存等自动行为 |
| Workspace | 统一文件与命令所在环境，核心提供接口 | `LocalWorkspace` 指向本次学习目录 |
| `RunContext` / deps | 应用向工具传递身份、连接和运行状态 | `LearningDeps.learner` 不由模型填写 |

`LocalWorkspace` 和 `PrepareTools` 属于 **Pydantic AI 核心**，不计入下面的 20 个 Harness 能力。`SubAgent`、`Reminder`、`Band`、`FileStore` 是配置或存储对象，也没有重复计数。

## 二十个能力分别做什么

| Harness 能力 | 在本例中的作用 | 默认演示如何观察 |
| --- | --- | --- |
| `InputGuardrail` | 模型请求前校验业务输入 | 正常输入放行；含“示例禁止”的输入可被拒绝 |
| `StepPersistence` | 保存步骤事件、快照和工具副作用状态 | 查看 `steps/`；程序结束时调用 `continue_run` 读回快照 |
| `ClampOversizedMessages` | 限制历史中单个超大文本片段 | 已配置 12,000 字符兜底；默认短流程不刻意触发 |
| `ClearToolResults` | 历史超过阈值后清理旧工具结果 | `messages.json` 出现中文“旧工具结果已清理”占位符 |
| `SlidingWindowCompaction` | 请求过长时只发送较近消息窗口 | 主流程持续运行到超过配置的 24 条消息阈值；完整细节可查快照 |
| `Memory` | 维护跨运行的 Markdown 笔记 | 实际调用写入、读取、搜索；查看 `memory/` |
| `FileSystem` | 读取资料、列目录和写报告 | 实际调用三个文件工具，生成 `report.md` |
| `Shell` | 在工作区执行命令 | 实际执行 `echo harness-demo`，工具返回标准输出 |
| `RepoContext` | 加载当前工作目录中的项目说明 | 自动读取本例生成的中文 `AGENTS.md` |
| `Skills` | 先发现技能，再按需加载正文 | 实际调用 `load_capability(id='study-notes')` |
| `Planning` | 给模型一份可更新的任务计划 | 实际写入计划、完成计划、读回；数据在 `plan.db` |
| `SystemReminders` | 每四次模型请求追加一次中文提醒 | 提醒作用于当前请求，不应在持久历史中不断累积 |
| `AskUser` | 验证问题与回答的结构，连接人机界面 | 离线明确打印“模拟回答”；真实模式会等待终端输入 |
| `SubAgents` | 将独立子任务委派给另一个 Agent | 实际运行 `reviewer` 子代理；离线审阅意见是固定测试文本 |
| `ConversationSearch` | 从持久化快照找回过去细节 | 实际搜索当前对话中的 `Harness`，与长期笔记搜索区分 |
| `ToolGuardrail` | 真正执行工具前检查调用 | 允许写 `report.md`；拒绝其他写入目标与记忆删除 |
| `ToolOutputLimits` | 长工具返回进入历史之前截短或溢出存储 | `long_reference` 返回长文本，实际触发 350 字符截断策略 |
| `WarnNearLimits` | 接近迭代预算时提醒收尾 | 演示后段会触发提醒；硬性停止由核心 `UsageLimits` 负责 |
| `ReportContextUsage` | 向应用发出上下文占用事件 | 每轮打印 `[上下文]`；教学模型的数值不是供应商计费数据 |
| `OutputGuardrail` | 最终输出交给应用前执行校验 | 最终文字包含“总结”才放行，否则要求重试 |

组合顺序也有含义：先对历史做压缩，再注入记忆；`Planning` 放在 `SystemReminders` 前面，避免把动态提醒当作计划提醒的缓存锚点。具体钩子的调用方向由核心组合机制决定，不能把列表简单理解成执行一次的流水线。

## 一次运行会发生什么

离线主代理按顺序进行 16 次工具调用：

1. 创建计划、列出目录、读取 `lesson.txt`。
2. 加载技能，询问学习方式，计算学习进度。
3. 执行 `echo`，获取长资料并触发截断，委派子代理审阅。
4. 写入、读回、搜索长期记忆，再搜索对话历史。
5. 写 `report.md`，把计划更新为完成，读回最终计划。

工具真正执行的是 Harness 和核心实现。固定剧本只决定模型“说什么”，不会直接调用文件工具内部方法，也不会绕过护栏。

`FunctionModel` 同时提供普通与流式入口，因为本例订阅了运行事件，核心运行路径可能使用流式模型请求。子代理的 `TestModel` 返回预先写好的文字，只用于验证委派链路，不能据此判断真实模型的审阅能力。

## 查看运行结果

每次运行使用新的 `output/<随机编号>/`，不会覆盖此前结果。此目录已在示例自己的 `.gitignore` 中排除。

| 产物 | 含义 |
| --- | --- |
| `report.md` | 文件工具实际写入的中文学习总结 |
| `messages.json` | 核心消息历史，可看到调用参数、返回结果、压缩后的占位符 |
| `tools.json` | 实际注册的工具中文说明及原始参数模式 |
| `plan.db` | `Planning` 的 SQLite 状态，不等同于对话历史 |
| `memory/` | `Memory` 的 Markdown 笔记及写入回执 |
| `steps/` | `StepPersistence` 的事件、快照、工具副作用记录 |
| `skills/study-notes/SKILL.md` | 本例 Agent 可以按需加载的中文技能 |
| `AGENTS.md`、`lesson.txt` | 本例工作区的说明和输入资料 |

这里每次都使用新的工作目录，所以不会自动读到上一次演示的记忆。要学习跨运行复用，应让两次 Agent 运行指向同一个工作区及存储，而不是误以为 `Memory` 会自动搜索所有历史目录。

`continue_run()` 只读回可继续使用的消息列表，不会自动恢复 Python 局部变量、工作区文件或所有能力状态，也不会保证外部副作用恰好执行一次。真实模型的下一轮可以把读回的 `history` 传给 `agent.run(..., message_history=history)`；离线剧本会从第一步重演，所以不要用它验证自主续接能力。

## 切换真实模型

综合示例接受 `--model provider:model`。先在同一个 Linux/WSL 虚拟环境中安装相应供应商的可选依赖，再按该供应商文档设置环境变量。不要在代码、报告、工具参数或提交中写密钥。

```bash
~/.cache/pydantic-ai-harness-learning-venv/bin/python harness_example/main.py --model "$HARNESS_MODEL" # 先将 HARNESS_MODEL 设为你有权限使用的 provider:model 标识。
```

真实模式会进行付费或本地模型请求，工具选择由模型决定，不保证用遍所有组件；遇到 `AskUser` 时需在终端输入答案。当前验证覆盖离线工具流程，没有调用真实模型服务。

## 本例没有启用的组件

| 类别 | 继续学习的方向 | 本例未启用的原因 |
| --- | --- | --- |
| 完整组合 | `Coder`、`Researcher` | 适合快速应用；当前先拆开组件学习，叠加 `Coder` 会重复提供文件等工具 |
| 代码执行与编排 | `CodeMode`、`DynamicWorkflow`、`BackgroundTools` | 增加解释器或并发语义，适合学完顺序工具流程后单独实验 |
| 模型辅助控制 | `Advisor`、`TrajectoryJudge`、`ToolCallJudge`、总结式压缩 | 需要额外模型调用；固定答案不能演示真实判断质量 |
| 计费与缓存 | `SpendLimits`、`WarnOnCacheBusts` | 离线教学模型没有真实供应商费用或提示缓存统计 |
| 外部服务 | 搜索、浏览器、GitHub、Slack、Linear 等 | 需要联网、账号或浏览器运行环境 |
| 执行隔离与耐久性 | 云沙箱、SSH、Bubblewrap、耐久执行引擎 | 需要额外基础设施；本地目录不是安全沙箱 |

这个示例关注通用能力的实际组合，不声称覆盖全部 Harness 导出类。需要不可信命令执行时，应使用真正隔离的工作区；`FileSystem` 路径限制不会约束 `Shell` 的整个进程权限。

## 对照源码和文档

- [官方 Harness 总览](https://pydantic.dev/docs/ai/harness/)：能力类别与核心/Harness 边界。
- [官方 Capabilities 概念](https://pydantic.dev/docs/ai/capabilities/overview/)：能力如何挂到核心 Agent。
- [仓库 Harness 文档](../docs/harness/index.md)：与本次检出最接近的说明。
- [Harness 能力源码](../src/pydantic_ai_harness/pydantic_ai_harness/)：每个能力有独立实现和 README。
- [核心 Agent 源码](../pydantic_ai_slim/pydantic_ai/agent/__init__.py)：运行参数和工具注册。
- [核心本地工作区源码](../pydantic_ai_slim/pydantic_ai/workspaces/local.py)：POSIX 限制、文件和命令后端。

Harness 处于 0.x 版本阶段。本例按照当前仓库 API 编写，升级后应重新检查签名并运行离线演示。
