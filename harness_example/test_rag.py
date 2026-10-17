"""测试真实 Agent 调用检索；HTTP 仅替换网络传输，不替换工具或响应校验."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from harness_example.rag import HttpRetrievalService, InMemoryRetrievalService, KnowledgeHit, KnowledgeResults, run_rag
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel


def retrieval_model(query: str) -> FunctionModel:
    """仅固定模型要查什么；最终答案从真实工具返回中读取，不预设检索结果."""
    called = False

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal called
        last_message = messages[-1]
        retry = isinstance(last_message, ModelRequest) and any(
            isinstance(part, RetryPromptPart) for part in last_message.parts
        )
        if not called or retry:
            assert 'search_knowledge' in {tool.name for tool in info.function_tools}
            called = True
            return ModelResponse(parts=[ToolCallPart('search_knowledge', {'query': query, 'limit': 2})])
        last_message = messages[-1]
        assert isinstance(last_message, ModelRequest)
        for part in last_message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name == 'search_knowledge':
                hits = KnowledgeResults.model_validate_json(part.model_response_str()).hits
                answer = '\n'.join(f'{hit.text} [来源]({hit.source})' for hit in hits) or '未找到依据'
                return ModelResponse(parts=[TextPart(answer)])
        raise AssertionError('没有收到真实检索工具的结果')

    return FunctionModel(respond)


def test_agent_retrieves_injected_documents_with_sources() -> None:
    """替换服务中的文档即可改变答案，来源随证据经过真实工具返回."""
    source = 'https://knowledge.example/team'
    service = InMemoryRetrievalService(
        documents=(KnowledgeHit(title='Team owner', text='维护者是 Lin。', source=source),)
    )
    result = asyncio.run(run_rag('查 Team owner', retrieval=service, model=retrieval_model('Team owner')))
    assert result.output == f'维护者是 Lin。 [来源]({source})'
    assert result.usage.tool_calls == 1
    assert result.usage.requests == 2


def test_unknown_query_does_not_fabricate_evidence() -> None:
    """无匹配的工具返回空列表，模型据此说明没有依据."""
    result = asyncio.run(run_rag('未知资料', model=retrieval_model('unmatched_xyz')))
    assert result.output == '未找到依据'


def test_default_documents_match_harness() -> None:
    """主流程使用 Harness 作为查询时可以获得带来源的教学资料."""
    hits = asyncio.run(InMemoryRetrievalService().search('Harness'))
    assert hits
    assert all(hit.source for hit in hits)


def test_http_service_through_real_agent() -> None:
    """验证 POST 契约、自定义鉴权、条数限制以及来源到最终答案的完整路径."""
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == 'POST'
        assert str(request.url) == 'https://retrieval.example/search'
        assert request.headers['Authorization'] == 'Bearer demo-token'
        assert json.loads(request.content) == {'query': 'policy', 'limit': 2}
        return httpx.Response(
            200,
            json={
                'hits': [
                    {'title': 'policy', 'text': f'规则 {number}', 'source': f'https://knowledge.example/{number}'}
                    for number in range(3)
                ]
            },
        )

    async def exercise() -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), headers={'Authorization': 'Bearer demo-token'}
        ) as client:
            service = HttpRetrievalService(client, 'https://retrieval.example/search')
            result = await run_rag('查询 policy', retrieval=service, model=retrieval_model('policy'))
            return result.output

    output = asyncio.run(exercise())
    assert len(requests) == 1
    assert '规则 0 [来源](https://knowledge.example/0)' in output
    assert '规则 1 [来源](https://knowledge.example/1)' in output
    assert '规则 2' not in output


def test_http_schema_requires_a_source() -> None:
    """来源字段缺失时明确暴露接口不匹配，避免生成不可追溯的答案."""

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={'hits': [{'title': 'bad', 'text': 'missing source'}]})
            )
        ) as client:
            with pytest.raises(ValidationError, match='source'):
                await HttpRetrievalService(client, 'https://retrieval.example/search').search('query')

    asyncio.run(exercise())


def test_http_response_size_is_bounded() -> None:
    """过大的外部响应在进入 JSON 校验和模型上下文之前被拒绝."""

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 101))
        ) as client:
            with pytest.raises(ValueError, match='100'):
                await HttpRetrievalService(client, 'https://retrieval.example/search', max_response_bytes=100).search(
                    'query'
                )

    asyncio.run(exercise())


def test_text_only_answer_is_not_claimed_as_rag() -> None:
    """没有调用检索工具时，独立示例不能声称已经执行 RAG."""
    with pytest.raises(RuntimeError, match='没有实际调用'):
        asyncio.run(run_rag(model=TestModel(call_tools=[], custom_output_text='我已经查过了。')))


def test_http_failure_can_retry_through_the_agent() -> None:
    """暂时的 HTTP 失败变成模型可见的重试，第二次请求仍由真实工具执行."""
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={'hits': [{'title': 'restored', 'text': '服务恢复', 'source': 'https://knowledge.example/status'}]},
        )

    async def exercise() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await run_rag(
                retrieval=HttpRetrievalService(client, 'https://retrieval.example/search'),
                model=retrieval_model('status'),
            )
            return result.output

    assert '服务恢复' in asyncio.run(exercise())
    assert attempts == 2
