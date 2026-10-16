"""Exercise the Ollama harness example without making model API requests."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

import pytest

from pydantic_ai import AgentRunResult, DeferredToolRequests
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.settings import ToolOrOutput
from pydantic_ai_harness.ask_user import TOOL_NAME
from pydantic_harness_example.main import ExampleConfig, LearningDeps, build_agent, run_interactive


@pytest.mark.parametrize(
    ('profile', 'compaction'),
    [('learning', 'sliding'), ('context', 'sliding'), ('context', 'clear')],
)
@pytest.mark.parametrize('json_args', [False, True], ids=['dict-args', 'json-args'])
def test_interactive_pause_and_resume(
    profile: Literal['learning', 'context'],
    compaction: Literal['sliding', 'clear'],
    json_args: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Require both tools and preserve the user's answer, conversation and budget across runs."""
    original_question = 'Harness 怎么组合工具和能力？'
    followup_question = '你希望看业务例子还是内部执行顺序？'
    user_answer = '内部执行顺序，最好有一个小例子。'
    final_answer = '模型选择工具，框架执行工具函数和 capability 钩子。'
    arguments = {
        'questions': [
            {
                'header': '学习方向',
                'question': followup_question,
                'options': [{'label': '业务例子'}, {'label': '内部执行顺序'}],
                'multi_select': False,
            }
        ]
    }
    responses = iter(
        [
            ModelResponse(parts=[TextPart('跳过工具直接回答。')]),
            ModelResponse(parts=[ToolCallPart('explain_concept', {'concept': '组合'}, 'concept-call')]),
            ModelResponse(parts=[TextPart('查询概念后直接回答，不追问。')]),
            ModelResponse(
                parts=[ToolCallPart(TOOL_NAME, json.dumps(arguments) if json_args else arguments, 'question-call')]
            ),
            ModelResponse(parts=[TextPart(final_answer)]),
        ]
    )
    model_requests: list[list[ModelMessage]] = []
    expected_tool_choices = iter(
        [
            ToolOrOutput(['explain_concept']),
            ToolOrOutput(['explain_concept']),
            ToolOrOutput([TOOL_NAME]),
            ToolOrOutput([TOOL_NAME]),
            'auto',
        ]
    )

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tools = {tool.name for tool in info.function_tools}
        assert {'explain_concept', TOOL_NAME} <= tools
        if profile == 'context':
            assert {'write_plan', 'read_plan', 'write_memory', 'read_memory'} <= tools
        else:
            assert tools == {'explain_concept', TOOL_NAME}
        assert info.model_settings is not None
        assert info.model_settings.get('tool_choice') == next(expected_tool_choices)
        model_requests.append(list(messages))
        return next(responses)

    inputs = iter([' ', original_question, '', user_answer])

    def read_input(prompt: str) -> str:
        return next(inputs)

    monkeypatch.setattr('builtins.input', read_input)
    config = ExampleConfig(profile=profile, compaction=compaction)
    deps = LearningDeps()

    async def exercise() -> AgentRunResult[str | DeferredToolRequests]:
        agent = build_agent(config)
        with agent.override(model=FunctionModel(respond)):
            async with agent:
                return await run_interactive(agent, deps, config)

    result = asyncio.run(exercise())

    assert result.output == final_answer
    assert deps.concept_explained
    assert deps.answers_received == 1
    assert len(model_requests) == result.usage.requests == 5
    # Host-provided deferred results are not successful local tool executions.
    assert result.usage.tool_calls == 1
    resumed_parts = [
        part for message in model_requests[-1] if isinstance(message, ModelRequest) for part in message.parts
    ]
    assert original_question in [part.content for part in resumed_parts if isinstance(part, UserPromptPart)]
    tool_returns = {part.tool_call_id: part for part in resumed_parts if isinstance(part, ToolReturnPart)}
    assert tool_returns['question-call'].content == {'学习方向': [user_answer]}
    retries = [part.content for part in resumed_parts if isinstance(part, RetryPromptPart)]
    assert len(retries) == 2
    assert 'explain_concept' in str(retries[0])
    assert TOOL_NAME in str(retries[1])
    assert result.conversation.deferred_tool_requests is None
    assert len({message.run_id for message in result.all_messages() if message.run_id is not None}) == 2
    assert {message.conversation_id for message in result.all_messages()} == {result.conversation.conversation_id}

    output = capsys.readouterr().out
    assert output.count('[cap.before_run]') == 2
    assert output.count('输入不能为空，请重新输入。') == 2
    assert followup_question in output
    assert final_answer in output


@pytest.mark.parametrize('compaction', ['sliding', 'clear'])
def test_context_stores_survive_deferred_run(compaction: Literal['sliding', 'clear']) -> None:
    """Plans and memory written before AskUser remain accessible after resuming."""
    note = '学习者偏好逐步解释。'
    plan_step = '解释工具执行顺序'
    responses = iter(
        [
            ModelResponse(
                parts=[
                    ToolCallPart('explain_concept', {'concept': '暂停恢复'}, 'concept-call'),
                    ToolCallPart(
                        'write_plan',
                        {'items': [{'id': 'explain', 'content': plan_step, 'status': 'in_progress'}]},
                        'write-plan',
                    ),
                    ToolCallPart('write_memory', {'content': note, 'file': 'MEMORY.md'}, 'write-memory'),
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        TOOL_NAME,
                        {
                            'questions': [
                                {
                                    'header': '细节',
                                    'question': '需要展示哪个环节？',
                                    'options': [{'label': '工具执行'}, {'label': '暂停恢复'}],
                                }
                            ]
                        },
                        'question-call',
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart('read_plan', {}, 'read-plan'),
                    ToolCallPart('read_memory', {'file': 'MEMORY.md'}, 'read-memory'),
                ]
            ),
            ModelResponse(parts=[TextPart('暂停后用同一 conversation 恢复。')]),
        ]
    )
    config = ExampleConfig(profile='context', compaction=compaction)

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return next(responses)

    async def exercise() -> AgentRunResult[str | DeferredToolRequests]:
        agent = build_agent(config)
        with agent.override(model=FunctionModel(respond)):
            async with agent:
                return await run_interactive(
                    agent, LearningDeps(), config, question='解释暂停恢复。', answer='暂停恢复'
                )

    result = asyncio.run(exercise())
    returns = {
        part.tool_call_id: part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    assert returns['read-memory'] == note + '\n'
    assert plan_step in str(returns['read-plan'])
    assert '1 in progress' in str(returns['read-plan'])
    assert returns['question-call'] == {'细节': ['暂停恢复']}
    assert result.usage.requests == 4
    assert result.usage.tool_calls == 5


@pytest.mark.skipif(os.name != 'posix', reason='LocalWorkspace currently requires POSIX.')
def test_coder_reads_workspace(tmp_path: Path) -> None:
    """The Coder composition registers its tools and reads through its configured workspace."""
    (tmp_path / 'notes.txt').write_text('Harness workspace test.', encoding='utf-8')
    responses = iter(
        [
            ModelResponse(
                parts=[
                    ToolCallPart('explain_concept', {'concept': '组合'}, 'concept-call'),
                    ToolCallPart('read_file', {'path': 'notes.txt'}, 'read-notes'),
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        TOOL_NAME,
                        {
                            'questions': [
                                {
                                    'header': '演示',
                                    'question': '接下来展示什么？',
                                    'options': [{'label': '读文件'}, {'label': '运行命令'}],
                                }
                            ]
                        },
                        'question-call',
                    )
                ]
            ),
            ModelResponse(parts=[TextPart('已读取学习工作区。')]),
        ]
    )
    config = ExampleConfig(profile='coder', workspace=tmp_path)

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tools = {tool.name for tool in info.function_tools}
        assert {'read_file', 'write_file', 'edit_file', 'list_files', 'grep', 'shell'} <= tools
        assert 'delegate_task' not in tools
        return next(responses)

    async def stream_response(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        response = await respond(messages, info)
        for index, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            else:
                assert isinstance(part, ToolCallPart)
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id
                    )
                }

    async def exercise() -> AgentRunResult[str | DeferredToolRequests]:
        agent = build_agent(config)
        with agent.override(model=FunctionModel(respond, stream_function=stream_response)):
            async with agent:
                return await run_interactive(agent, LearningDeps(), config, question='读取笔记。', answer='读文件')

    result = asyncio.run(exercise())
    read_results = [
        part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_call_id == 'read-notes'
    ]
    assert len(read_results) == 1
    assert 'Harness workspace test.' in str(read_results[0])
    assert result.usage.requests == 3
    assert result.usage.tool_calls == 2


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows guard.')
def test_coder_explains_windows_workspace_requirement(tmp_path: Path) -> None:
    """Explain how to run Coder before creating its workspace on native Windows."""
    workspace = tmp_path / 'workspace'
    with pytest.raises(RuntimeError, match='VS Code Remote - WSL'):
        build_agent(ExampleConfig(profile='coder', workspace=workspace))
    assert not workspace.exists()


@pytest.mark.parametrize(('requests', 'tools'), [(0, 1), (1, 0)])
def test_usage_limits_must_be_positive(requests: int, tools: int) -> None:
    """Reject an unusable model or tool budget before starting an agent."""
    with pytest.raises(ValueError, match='正整数'):
        ExampleConfig(request_limit=requests, tool_calls_limit=tools)
