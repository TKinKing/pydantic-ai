"""离线教学模型：只替代模型决策，工具、护栏、事件和持久化仍由真实 Agent 执行."""  # 固定剧本不具备推理能力。

import json  # 把核心工具调用中的参数字典编码为流式模型需要的 JSON 文本。
from collections.abc import AsyncIterator  # 核心的流式请求需要异步产生响应片段。

from pydantic_ai.messages import (  # 核心统一消息类型，模型供应商之间共享此抽象。
    ModelMessage,  # 模型请求和响应的联合类型。
    ModelRequest,  # 发给模型的请求，可包含用户输入与工具结果。
    ModelResponse,  # 模型返回的文本或工具调用。
    RetryPromptPart,  # 工具参数或输出校验失败后发给模型的重试提示。
    TextPart,  # 文本响应片段。
    ToolCallPart,  # 模型提出的工具名称和参数，不等于工具已经执行。
)  # 核心消息。
from pydantic_ai.models.function import (  # 导入教学模型接口。
    AgentInfo,  # 模型可见的工具和指令。
    DeltaToolCall,  # 单个工具调用的流式片段。
    DeltaToolCalls,  # 流式工具片段的索引映射。
    FunctionModel,  # 将 Python 函数适配为模型。
)  # 普通与流式教学模型接口。


def make_offline_model() -> FunctionModel:  # 每个运行创建新模型，避免演示步骤计数跨运行串联。
    """按顺序发出工具调用，让读者每次都能观察相同的 Harness 工作过程."""  # 调用参数由示例作者固定。
    calls = [  # 每次只发一个工具调用，让有先后依赖的动作按顺序完成。
        ToolCallPart(  # 第一步创建当前计划。
            'write_plan',  # 首次调用写计划工具。
            {'items': [{'content': '学习 Harness 并写总结', 'status': 'in_progress'}]},  # 初始状态为进行中。
        ),  # 制定计划。
        ToolCallPart('list_directory', {'path': '.'}),  # 发现学习工作区的文件。
        ToolCallPart('read_file', {'path': 'lesson.txt'}),  # 读取真实文件，内容由 main.py 初始化。
        ToolCallPart('load_capability', {'id': 'study-notes'}),  # 按需加载技能正文，而非把所有技能塞入初始提示。
        ToolCallPart(  # 提问也是模型调用工具的一部分。
            'ask_user_question',  # AskUser 负责问题模式校验，回答界面由应用提供。
            {  # AskUser 的工具参数对象。
                'questions': [  # 一次调用可包含多个问题。
                    {  # 本例仅询问一个学习偏好。
                        'header': '学习方式',  # 回答通过此短标题关联到问题。
                        'question': '选择学习方式',  # 给用户看的问题正文。
                        'options': [  # 一个结构化问题。
                            {  # 第一个可选择的答案。
                                'label': '先看例子',  # 模拟回答用这个标签表达选择。
                                'description': '先运行再阅读中文注释',  # 解释这个选项的含义。
                            },  # 离线模式明确使用此模拟选项。
                            {  # 第二个选项仅用来展示问题结构。
                                'label': '先看概念',  # 另一个学习方式的名称。
                                'description': '先阅读组件关系再运行',  # 说明这个候选项的含义。
                            },  # 保留第二个选项以展示提问模式，本例固定选择第一项。
                        ],  # 选项列表结束。
                    }  # 当前问题定义结束。
                ]  # 问题列表结束。
            },  # 问题参数结束。
        ),  # 提问调用结束。
        ToolCallPart('learning_progress', {'completed': 2, 'total': 3}),  # 自定义工具通过 RunContext 访问用户依赖。
        ToolCallPart('run_command', {'command': 'echo harness-demo'}),  # 执行无副作用的命令，展示 Shell 工具。
        ToolCallPart('long_reference', {}),  # 产生长工具结果，实际触发输出截断。
        ToolCallPart(  # 主代理提供完整任务背景，子代理不会自动继承主对话。
            'delegate_task',  # SubAgents 注册的委派工具。
            {  # 委派工具的参数。
                'agent_name': 'reviewer',  # 对应 build_agent 中注册的子代理名称。
                'task': '检查这个解释：Agent 管循环，Harness 能力提供可选工具和钩子。',  # 必须把审阅对象写入任务。
            },  # 子任务。
        ),  # 子代理只返回检查意见，不直接操作父代理的文件。
        ToolCallPart(  # 主代理主动记录长期可复用的事实。
            'write_memory',  # 调用长期记忆写入工具。
            {'content': '学习结论：Agent 管循环，Harness 通过 capabilities 组合能力。'},  # 追加到主笔记。
        ),  # 保存记忆。
        ToolCallPart('read_memory', {'file': 'MEMORY.md'}),  # 读回刚刚写入的长期笔记。
        ToolCallPart('search_memory', {'query': 'Harness'}),  # 搜索保存的笔记。
        ToolCallPart('search_conversation_history', {'query': 'Harness'}),  # 检索 StepPersistence 保存的原始对话快照。
        ToolCallPart(  # 模型请求写入学习总结；护栏会检查目标文件名。
            'write_file',  # FileSystem 执行实际写入。
            {  # 写文件参数由 FileSystem 工具模式验证。
                'path': 'report.md',  # 工作区内的相对路径，同时满足本例护栏规则。
                'content': '# 学习总结\n\nAgent 负责循环；Harness 提供工具、记忆、计划和钩子。\n',  # 写入的报告正文。
            },  # 中文正文。
        ),  # 文件写入调用结束。
        ToolCallPart(  # 本例使用全量替换计划，避免引入任务标识的额外解析。
            'write_plan',  # 再次写计划以更新状态。
            {'items': [{'content': '学习 Harness 并写总结', 'status': 'completed'}]},  # 将当前计划置为完成。
        ),  # 完成计划。
        ToolCallPart('read_plan', {}),  # 读回最终计划，确认任务状态。
    ]  # 一共十六次真实工具调用；无需模型服务。
    step = 0  # 演示计数存在模型闭包中，不依赖会被压缩的消息历史。

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:  # 与 FunctionModel 要求的签名一致。
        """返回下一条工具请求；遇到参数重试立即报错，避免演示掩盖工具调用错误."""  # 真实模型通常会自行纠错。
        nonlocal step  # 同一轮演示的多次模型请求共享当前步骤。
        for message in messages:  # 固定剧本不预期任何重试；也检查请求尾部教学提醒之前的工具结果。
            if isinstance(message, ModelRequest):  # 核心请求消息可包含工具返回或重试提示。
                for part in message.parts:  # 一个请求可能携带多种消息片段。
                    if isinstance(part, RetryPromptPart):  # 参数不合法等问题会产生这种核心重试消息。
                        raise RuntimeError(f'离线剧本的工具调用失败：{part.content}')  # 让集成错误可见。
        if step < len(calls):  # 尚有工具要调用时继续执行剧本。
            call = calls[step]  # 取出本次模型应发出的调用。
            available = {tool.name for tool in info.function_tools}  # 框架完成能力挂载后实际提供给模型的工具。
            if call.tool_name not in available:  # 检查工具真的存在，不能只在示例中写一个名称。
                raise RuntimeError(f'当前未注册工具：{call.tool_name}；可用工具：{sorted(available)}')  # 显示注册问题。
            step += 1  # 只有成功选择一个工具后才推进教学步骤。
            print(f'[离线模型 {step:02d}] 调用 {call.tool_name}')  # 终端展示模型决策和工具执行的分界。
            return ModelResponse(parts=[call])  # 核心 Agent 接收此消息后实际调用 Harness 工具。
        return ModelResponse(parts=[TextPart('学习总结：计划已完成，报告和长期记忆已保存。')])  # 结束模型工具循环。

    async def stream(  # 适配核心的流式请求接口。
        messages: list[ModelMessage],  # 当前请求的消息历史。
        info: AgentInfo,  # 接收历史与当前工具目录。
    ) -> AsyncIterator[str | DeltaToolCalls]:  # 支持流式循环。
        """把同一剧本的完整响应转换为流式片段，事件订阅时核心可以使用这个入口."""  # 不重复执行工具。
        response = respond(messages, info)  # 统一决定本轮输出，普通与流式入口使用相同逻辑。
        for index, part in enumerate(response.parts):  # 当前剧本每次只有一个工具调用或一段文字。
            if isinstance(part, ToolCallPart):  # 工具参数以 JSON 字符串传入流式增量接口。
                yield {  # 产生一个工具增量。
                    index: DeltaToolCall(  # 按片段位置标识工具调用。
                        name=part.tool_name,  # 将当前工具名称交给核心流式解析器。
                        json_args=json.dumps(part.args_as_dict()),  # 工具名称与序列化后的参数。
                    )  # 将名称和 JSON 参数交给核心。
                }  # 组装工具调用。
            elif isinstance(part, TextPart):  # 最终中文回答对应文本增量。
                yield part.content  # 核心收到文字后继续执行输出校验与结束钩子。

    return FunctionModel(respond, stream_function=stream)  # 同时支持普通请求与流式请求。


def make_reviewer_model() -> FunctionModel:
    """离线子代理只检查调用链，不模拟真实模型的审阅质量."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart('概念检查：Agent 管理循环，Harness 通过能力组合行为。')])

    return FunctionModel(respond)
