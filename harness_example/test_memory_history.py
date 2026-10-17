"""Exercise real Memory/compaction hooks with a deterministic model and no external API calls."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from harness_example.memory_history import (
    MEMORY_FACT,
    MemoryUser,
    build_memory_agent,
    demonstrate_history,
    demonstrate_memory,
    load_history,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ToolOrOutput


@pytest.mark.skipif(os.name == 'nt', reason='FileStore uses the POSIX LocalWorkspace backend.')
def test_memory_survives_new_agent_and_conversation_but_not_new_user(tmp_path: Path) -> None:
    """Persist a real tool write and inject it only into the matching user namespace."""
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        text = ModelMessagesTypeAdapter.dump_json(messages).decode()
        if calls == 1:
            # Saying it is saved is insufficient: the real output validator must retry.
            return ModelResponse(parts=[TextPart('已保存。')])
        if calls == 2:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
            return ModelResponse(parts=[ToolCallPart('write_memory', {'content': MEMORY_FACT, 'file': 'MEMORY.md'})])
        if calls == 3:
            assert any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts)
            return ModelResponse(parts=[TextPart('已通过工具保存。')])
        assert calls == 4
        assert len(messages) == 1  # The new conversation did not receive previous messages.
        assert MEMORY_FACT in text  # Memory injected the persisted file into this new request.
        assert info.model_settings is not None
        assert info.model_settings.get('tool_choice') == ToolOrOutput([])
        return ModelResponse(parts=[TextPart(MEMORY_FACT)])

    def other_user(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert MEMORY_FACT not in ModelMessagesTypeAdapter.dump_json(messages).decode()
        return ModelResponse(parts=[TextPart('没有记录。')])

    async def exercise() -> None:
        first, second = await demonstrate_memory(workspace=tmp_path, model=FunctionModel(respond))
        assert first.conversation_id != second.conversation_id
        assert first.run_id != second.run_id
        assert second.output == MEMORY_FACT
        assert len(second.all_messages()) == 2
        assert (tmp_path / 'memory' / 'learner-001' / 'main' / 'MEMORY.md').read_text(
            encoding='utf-8'
        ).strip() == MEMORY_FACT
        request = (tmp_path / 'memory_new_conversation_request.json').read_text(encoding='utf-8')
        assert MEMORY_FACT in request
        # The automatic memory injection is a request view, not copied conversation history.
        assert MEMORY_FACT not in ModelMessagesTypeAdapter.dump_json(second.all_messages()[:1]).decode()

        agent = build_memory_agent(
            workspace=tmp_path, model=FunctionModel(other_user), request_path=tmp_path / 'other.json'
        )
        async with agent:
            result = await agent.run('我偏好怎样学习？', deps=MemoryUser('learner-002'))
        assert result.output == '没有记录。'

    asyncio.run(exercise())
    assert calls == 4


def test_ten_thousand_archived_messages_are_not_all_sent_to_model(tmp_path: Path) -> None:
    """Preserve the archive while observing bounded windows and actual incremental summary calls."""
    calls = 0
    first_summary = '## Intent\n课程代号 ORCHID-42；目标是理解 Harness。\n## Current state\n已处理第一批。'
    updated_summary = first_summary.replace('第一批', '第二批')

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        text = ModelMessagesTypeAdapter.dump_json(messages).decode()
        if calls == 1:
            assert len(messages) <= 20
            assert '第5000轮' in text
            assert 'ORCHID-42' not in text  # Sliding windows discard the old fact; they do not summarize it.
            return ModelResponse(parts=[TextPart('最近在继续学习；课程代号不在当前窗口中。')])
        if calls == 2:
            assert 'ORCHID-42' in text and '第5000轮' not in text
            assert '<previous-summary>' not in text
            return ModelResponse(parts=[TextPart(first_summary)])
        if calls == 3:
            assert '<previous-summary>' in text
            assert 'ORCHID-42' in text and '第一批' in text
            assert '第60轮' not in text  # Recent tail stays intact rather than entering this summary call.
            return ModelResponse(parts=[TextPart(updated_summary)])
        assert calls == 4
        assert len(messages) < 20
        assert '第二批' in text and 'ORCHID-42' in text and '第60轮' in text
        assert '第5000轮' not in text
        return ModelResponse(parts=[TextPart('前120条教学消息的课程代号为 ORCHID-42。')])

    sliding, summarized = asyncio.run(demonstrate_history(workspace=tmp_path, model=FunctionModel(respond)))
    archive = load_history(tmp_path / 'full_history.json')
    assert len(archive) == 10_000
    assert 'ORCHID-42' in ModelMessagesTypeAdapter.dump_json(archive[:1]).decode()
    assert '第5000轮' in ModelMessagesTypeAdapter.dump_json(archive[-2:]).decode()
    assert len(sliding.all_messages()) <= 21
    assert summarized.usage.requests == 3  # Two summary calls plus the final response.
    counts = json.loads((tmp_path / 'history_counts.json').read_text(encoding='utf-8'))
    assert counts['archive_messages'] == 10_000
    assert counts['summary_covered_messages'] == 120
    assert counts['summary_model_requests'] == 2
    window = ModelMessagesTypeAdapter.validate_json((tmp_path / 'summary_window.json').read_bytes())
    assert len(window) < 20
    assert 'ORCHID-42' in ModelMessagesTypeAdapter.dump_json(window).decode()
    assert calls == 4


def test_history_reopens_owned_http_client_for_manual_compaction(tmp_path: Path) -> None:
    """Use real HTTP clients to cover the gap between Agent contexts and compact_now."""
    requests: list[bytes] = []

    async def reply(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            headers = (await reader.readuntil(b'\r\n\r\n')).decode()
            length = next(
                int(line.split(':', 1)[1])
                for line in headers.splitlines()
                if line.lower().startswith('content-length:')
            )
            requests.append(await reader.readexactly(length))
            body = json.dumps(
                {
                    'id': f'local-{len(requests)}',
                    'object': 'chat.completion',
                    'created': 0,
                    'model': 'local-test',
                    'choices': [
                        {
                            'index': 0,
                            'message': {'role': 'assistant', 'content': '课程代号 ORCHID-42。'},
                            'finish_reason': 'stop',
                        }
                    ],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
                },
                ensure_ascii=False,
            ).encode()
            writer.write(
                f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def exercise() -> None:
        async with asyncio.TaskGroup() as tasks:
            server = await asyncio.start_server(
                lambda reader, writer: tasks.create_task(reply(reader, writer)), '127.0.0.1', 0
            )
            async with server:
                port = server.sockets[0].getsockname()[1]
                provider = OllamaProvider(base_url=f'http://127.0.0.1:{port}/v1', api_key='local-test')
                model = OpenAIChatModel('local-test', provider=provider)
                await demonstrate_history(workspace=tmp_path, model=model)
                assert provider.client.is_closed()
        assert len(requests) == 4
        assert 'previous-summary' in requests[2].decode()

    asyncio.run(exercise())
