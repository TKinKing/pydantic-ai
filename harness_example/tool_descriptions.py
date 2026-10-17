"""内置工具的中文索引：替换给模型看的工具说明，同时保留原始参数模式."""  # 不改 Harness 源码。

TOOL_DESCRIPTIONS: dict[str, str] = {  # 工具名称必须与当前源码注册的名称一致。
    'read_file': '读取工作区文件；path 是路径，offset/limit 控制分页。供 Agent 获取真实资料。',  # 所属能力：FileSystem。
    'write_file': '写入工作区文件；path 是路径，content 是完整正文。示例只允许写 report.md。',  # 所属能力：FileSystem。
    'list_directory': '列出目录；path 指定工作区中的目录。供 Agent 发现可读文件。',  # 所属能力：FileSystem。
    'run_command': '运行命令；command 是命令文本，timeout 是秒数。本例只允许 echo。',  # 所属能力：Shell。
    'write_plan': '用 items 替换完整计划；每项含 content 和 status，可选 active_form。',  # 所属能力：Planning。
    'read_plan': '读取当前计划及状态，供 Agent 检查还有哪些步骤未完成。',  # 所属能力：Planning。
    'write_memory': '保存跨运行笔记；content 为正文，file 默认 MEMORY.md，old_text 可精确替换旧段落。',  # 所属能力：Memory。
    'read_memory': '读取长期笔记；file 是笔记文件名，与本轮 message_history 不同。',  # 所属能力：Memory。
    'search_memory': '用 query 搜索长期笔记，供 Agent 找回以往记录的事实。',  # 所属能力：Memory。
    'delete_memory': '删除 file 指定的笔记；主笔记受保护。本学习示例的工具护栏会拒绝删除。',  # 所属能力：Memory。
    'load_capability': '按 id 加载延迟能力；这里用来加载 study-notes 技能的中文操作指引。',  # Skills 与核心加载器。
    'delegate_task': '委派独立任务；agent_name 选子代理，task 写完整任务背景，子代理不自动看到父对话。',  # 所属能力：SubAgents。
    'ask_user_question': '向人提问；questions 含 header、question、options 和可选 multi_select。',  # 所属能力：AskUser。
    'search_conversation_history': '用 query 搜索已保存的对话快照；可用 run_id 限定某轮运行。',  # 所属能力：ConversationSearch。
    'read_tool_result': '按 handle 分页读取溢出保存的工具结果；offset/limit 控制范围，pattern 可筛选文本。',  # 所属能力：ToolOutputLimits。
    'learning_progress': '计算学习进度；completed 是已完成数，total 是总数，用户名称从依赖注入取得。',  # 自定义工具。
    'long_reference': '返回一份较长的中文参考资料，用来观察 ToolOutputLimits 如何缩短工具结果。',  # 自定义工具。
    'search_knowledge': '检索应用注入的知识库；query 是问题，返回内容与来源，回答时引用来源。',  # 自定义 RAG 能力。
    'mcp_add': '通过独立 MCP 服务计算 a 加 b；参数是两个整数。',  # 核心 MCP 能力提供的远程工具。
    'mcp_echo': '通过独立 MCP 服务返回 text，用于观察请求和响应。',  # MCP 教学服务。
}  # 本例启用的工具均有中文说明；新增工具时也应扩充这个索引。
