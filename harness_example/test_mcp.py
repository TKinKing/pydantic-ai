"""真实启动 stdio 服务，验证 MCP 发现、调用和 Agent 集成；不访问模型 API."""

import asyncio

import pytest

from harness_example import mcp_client
from harness_example.mcp_client import create_mcp_capability
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def test_stdio_mcp_tools_through_agent() -> None:
    """进程边界是测试目标：真实服务进程提供工具，FunctionModel 只固定调用决策."""
    requests = 0

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        assert {tool.name for tool in info.function_tools} == {'mcp_add', 'mcp_echo'}
        requests += 1
        if requests == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart('mcp_add', {'a': 7, 'b': 5}, 'add'),
                    ToolCallPart('mcp_echo', {'text': '真实 MCP 往返'}, 'echo'),
                ]
            )
        results = {
            part.tool_call_id: part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        assert results == {'add': 12, 'echo': '真实 MCP 往返'}
        return ModelResponse(parts=[TextPart('两个工具都经过真实 stdio 服务执行。')])

    async def exercise() -> None:
        capability = create_mcp_capability()
        toolset = capability.local
        assert isinstance(toolset, MCPToolset)
        agent = Agent(FunctionModel(respond), capabilities=[capability])
        async with asyncio.timeout(30), agent:
            assert {tool.name for tool in await toolset.list_tools()} == {'mcp_add', 'mcp_echo'}
            assert await toolset.direct_call_tool('mcp_add', {'a': -2, 'b': 5}) == 3
            assert await toolset.direct_call_tool('mcp_echo', {'text': '直接调用'}) == '直接调用'
            result = await agent.run('通过 MCP 调用加法和中文回显。')
        assert result.output == '两个工具都经过真实 stdio 服务执行。'
        assert result.usage.tool_calls == 2
        assert requests == 2

    asyncio.run(exercise())


@pytest.mark.parametrize('tool_names', [(), ('mcp_add',), ('mcp_add', 'mcp_echo')])
def test_client_requires_both_tools(monkeypatch: pytest.MonkeyPatch, tool_names: tuple[str, ...]) -> None:
    """入口不能把没有执行工具、或只执行一个工具的回答当作连接演示成功."""
    calls = {
        'mcp_add': ToolCallPart('mcp_add', {'a': 7, 'b': 5}),
        'mcp_echo': ToolCallPart('mcp_echo', {'text': '我已连通 MCP'}),
    }
    called = False

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal called
        if tool_names and not called:
            called = True
            return ModelResponse(parts=[calls[name] for name in tool_names])
        return ModelResponse(parts=[TextPart('声称两个工具都已执行。')])

    monkeypatch.setattr(mcp_client, 'create_model', lambda: FunctionModel(respond))
    if len(tool_names) == 2:
        asyncio.run(mcp_client.main())
    else:
        with pytest.raises(RuntimeError, match='mcp_add 和 mcp_echo'):
            asyncio.run(mcp_client.main())
