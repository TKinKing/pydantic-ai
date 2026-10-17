"""先读这个最小示例：核心 Agent 加上 Harness 的 Planning，就能维护任务计划."""  # 中文学习入口。

from pydantic_ai import Agent  # 核心执行器：负责模型请求、工具调用循环和最终输出。
from pydantic_ai.models.test import TestModel  # 核心测试模型：无需联网，按工具的参数模式生成测试数据。
from pydantic_ai_harness import Planning  # Harness 能力：为 Agent 添加计划工具和计划提醒。

agent = Agent(  # Harness 不另建一套 Agent，而是组合到 Pydantic AI 的 Agent 中。
    TestModel(call_tools=['read_plan'], custom_output_text='已读取计划；当前还没有任务。'),  # 只调用只读工具。
    capabilities=[  # 把 Harness 提供的能力挂到核心 Agent 上。
        Planning(  # 配置计划能力。
            tools=['read_plan'],  # 最小示例仅开放读取计划。
            guidance='使用 read_plan 查看计划；本例不提供创建或更新计划的工具。',  # 中文指令只描述实际可用能力。
            descriptions={'read_plan': '读取当前任务计划及完成情况。'},  # 中文描述帮助模型理解工具用途。
        )  # 仅开放一个只读计划工具。
    ],  # 挂载能力。
)  # Agent 构造结束；到 run_sync 时才真正开始执行。

if __name__ == '__main__':  # 直接运行本文件时演示；导入本文件不会自动调用模型。
    result = agent.run_sync('请读取当前计划。')  # 同步入口内部驱动异步的 Agent 运行循环。
