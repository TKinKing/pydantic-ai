"""连接最小 stdio MCP 服务：python -m harness_example.mcp_client，无需参数."""

import asyncio
import sys
from pathlib import Path

from fastmcp.client.transports import StdioTransport

from harness_example.model_config import create_model
from pydantic_ai import Agent
from pydantic_ai.capabilities import MCP
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.usage import UsageLimits


def create_mcp_capability() -> MCP[object]:
    """构造核心 MCP 能力；不依赖业务 deps，可直接加入完整 Harness 示例."""
    transport = StdioTransport(
        command=sys.executable,
        args=[str(Path(__file__).with_name('mcp_server.py').resolve())],
    )
    toolset = MCPToolset[object](
        transport,
        id='learning-mcp',
        include_instructions=True,
        init_timeout=60,
        read_timeout=300,  # 为服务端断点留出观察时间，避免刚停下就让客户端超时。
    )
    # 工具名在服务端直接带 mcp_ 前缀；这里不会添加另一个前缀。
    return MCP(local=toolset, id='learning-mcp')


async def main() -> None:
    """模型选择工具，核心 MCP 能力通过 stdio 让服务进程执行工具."""
    model = create_model()
    agent = Agent(
        model,
        capabilities=[create_mcp_capability()],
        instructions='请用中文回答。计算必须调用 mcp_add，回显必须调用 mcp_echo。',
        model_settings={'temperature': 0, 'max_tokens': 512},
    )
    # 这个作用域管理 MCP 服务进程和连接，结束时关闭它们。
    async with agent:
        result = await agent.run(
            '请先计算 7 + 5，再回显“我已连通 MCP”，最后说明两个工具的返回值。',
            usage_limits=UsageLimits(request_limit=6, tool_calls_limit=4),
        )
    completed_tools = {
        part.tool_name
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    if not {'mcp_add', 'mcp_echo'} <= completed_tools:
        raise RuntimeError('模型没有实际完成 mcp_add 和 mcp_echo，不能把普通回答当成 MCP 演示已完成。')


if __name__ == '__main__':
    asyncio.run(main())
