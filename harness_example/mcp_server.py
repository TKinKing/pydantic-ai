"""最小 MCP 服务：由客户端用当前 Python 启动，stdio 只用于协议通信."""

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    'Harness learning MCP',
    instructions='使用 mcp_add 做整数加法，使用 mcp_echo 原样返回文字。两个工具都没有外部副作用。',
    log_level='WARNING',
)


@server.tool()
def mcp_add(a: int, b: int) -> int:
    """返回两个整数之和，演示跨进程传递工具参数和结果."""
    return a + b


@server.tool()
def mcp_echo(text: str) -> str:
    """原样返回文字，便于观察中文通过 MCP 协议往返."""
    return text


if __name__ == '__main__':
    # 不向 stdout 打印日志：客户端在这里读写 MCP 协议消息。
    server.run(transport='stdio')
