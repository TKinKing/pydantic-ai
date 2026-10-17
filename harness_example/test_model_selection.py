"""Check provider selection and the request built by a real Agent, without API calls."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from harness_example import main as example
from pydantic_ai import Agent
from pydantic_ai.settings import ToolOrOutput


class RequestCaptured(Exception):
    """Stop at the SDK boundary before sending a request."""


@pytest.mark.parametrize('api_key', ['', ' \t ', ' test-key-not-real '])
def test_model_selection_and_request_settings(monkeypatch: pytest.MonkeyPatch, api_key: str) -> None:
    """Keep local fallback and DeepSeek's non-thinking tool requests compatible."""
    monkeypatch.setattr(example, 'DEEPSEEK_API_KEY', api_key)

    async def exercise() -> None:
        model = example.create_model()
        if api_key.strip():
            assert model.system == 'deepseek'
            assert model.model_name == example.DEEPSEEK_MODEL
            assert str(model.base_url).rstrip('/') == 'https://api.deepseek.com'
            assert model.client.api_key == api_key.strip()
        else:
            assert model.system == 'ollama'
            assert model.model_name == example.OLLAMA_MODEL
            assert str(model.base_url).rstrip('/') == example.OLLAMA_BASE_URL.rstrip('/')

        agent = Agent(model, model_settings={'tool_choice': ToolOrOutput(['read_file'])})

        def read_file() -> str:
            return 'example'

        agent.tool_plain(read_file)
        capture = AsyncMock(side_effect=RequestCaptured)
        with patch.object(model.client.chat.completions, 'create', capture), pytest.raises(RequestCaptured):
            await agent.run('Read the example.')

        capture.assert_awaited_once()
        request = capture.call_args.kwargs
        assert request['model'] == model.model_name
        assert [tool['function']['name'] for tool in request['tools']] == ['read_file']
        if api_key.strip():
            # DeepSeek accepts reasoning_effort='none' to disable thinking.
            assert request['reasoning_effort'] == 'none'

    asyncio.run(exercise())
