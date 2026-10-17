"""Verify the complete example through real Agent/Harness pipelines without model API calls."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from harness_example.main import LESSON_STEPS, LearningDeps, build_agent, prepare_workspace, run_example
from harness_example.offline_model import make_offline_model, make_reviewer_model
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
from pydantic_ai_harness.guardrails import InputBlocked
from pydantic_ai_harness.planning import PlanItem, SqlitePlanStore, TaskStatus
from pydantic_ai_harness.step_persistence import ContinuableSnapshot, FileStepStore


class ProbeFinished(Exception):
    """Stop a short model probe after its assertions have observed the real retry."""


def scripted_model(respond: Callable[[list[ModelMessage], AgentInfo], ModelResponse]) -> FunctionModel:
    """Support the streaming path used by the example's event subscribers."""

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        for index, part in enumerate(respond(messages, info).parts):
            if isinstance(part, ToolCallPart):
                yield {index: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args_as_dict()))}
            elif isinstance(part, TextPart):
                yield part.content

    return FunctionModel(respond, stream_function=stream)


def test_offline_walkthrough_and_snapshot_continuation(tmp_path: Path) -> None:
    """Run the tools, persist their artifacts and continue without repeating side effects."""

    async def exercise() -> None:
        result = await run_example(workspace=tmp_path, model=make_offline_model(), reviewer_model=make_reviewer_model())
        evidence = json.loads((tmp_path / 'coverage.json').read_text(encoding='utf-8'))
        assert len(evidence['completed_steps']) == len(LESSON_STEPS)
        assert evidence['completed_tools'].count('write_file') == 1
        assert evidence['completed_tools'].count('write_memory') == 1
        assert evidence['successful_delegations'] == 1
        assert evidence['context_events'] >= 18
        assert evidence['continued_from_snapshot']
        assert 'Agent 负责循环' in (tmp_path / 'report.md').read_text(encoding='utf-8')
        memory = list((tmp_path / 'memory').rglob('MEMORY.md'))
        assert len(memory) == 1
        assert 'Harness 通过 capabilities' in memory[0].read_text(encoding='utf-8')
        items = await SqlitePlanStore(str(tmp_path / 'plan.db')).get_items()
        assert len(items) == 1 and items[0].status is TaskStatus.completed
        assert (tmp_path / 'tools.json').exists()
        assert (tmp_path / 'continued_messages.json').exists()
        assert '[harness-learning-step]' not in (tmp_path / 'messages.json').read_text(encoding='utf-8')
        assert '[harness-learning-step]' not in (tmp_path / 'continued_messages.json').read_text(encoding='utf-8')

        store = FileStepStore(tmp_path / 'steps')
        runs = await store.list_runs(conversation_id=result.conversation_id)
        assert len(runs) == 2
        assert runs[0].run_id != runs[1].run_id == result.run_id
        first_events = await store.list_events(run_id=runs[0].run_id)
        second_events = await store.list_events(run_id=runs[1].run_id)
        completed = [event for event in first_events if event.kind == 'tool_call_completed']
        assert len(completed) == len(LESSON_STEPS)
        assert not any(event.kind.startswith('tool_call') for event in second_events)
        assert result.usage.requests == len(LESSON_STEPS) + 3  # Tools, final answer, child and resumed request.
        assert not any(isinstance(part, ToolCallPart) for message in result.new_messages() for part in message.parts)
        for event in completed:
            assert event.tool_call_id is not None
            effect = await store.get_tool_effect(run_id=runs[0].run_id, tool_call_id=event.tool_call_id)
            assert effect is not None and effect.status == 'completed'

        snapshots = sorted(
            (
                TypeAdapter(ContinuableSnapshot).validate_json(path.read_bytes())
                for path in (tmp_path / 'steps' / runs[0].run_id / 'snapshots').glob('*.json')
            ),
            key=lambda snapshot: snapshot.step_index,
        )
        sizes = [len(snapshot.messages) for snapshot in snapshots]
        assert any(after < before for before, after in zip(sizes, sizes[1:]))  # Sliding window actually ran.
        returns = [
            part
            for snapshot in snapshots
            for message in snapshot.messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert any(part.content == '[旧工具结果已清理，可搜索历史]' for part in returns)
        assert any(part.tool_name == 'mcp_add' and '12' in str(part.content) for part in returns)
        assert any(part.tool_name == 'search_knowledge' and 'source' in str(part.content) for part in returns)
        limited = [
            part.content
            for part in returns
            if part.tool_name == 'long_reference' and isinstance(part.content, str) and 'truncated:' in part.content
        ]
        assert limited and all(len(content) <= 350 for content in limited)

    asyncio.run(exercise())


def test_premature_output_requests_tool_without_advancing(tmp_path: Path) -> None:
    """A textual claim of completion cannot bypass the guided tool sequence."""
    deps = LearningDeps()
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        latest = messages[-1]
        assert isinstance(latest, ModelRequest)
        assert any(
            isinstance(part, UserPromptPart)
            and '[harness-learning-step]' in str(part.content)
            and 'write_plan' in str(part.content)
            for part in latest.parts
        )
        if calls == 1:
            return ModelResponse(parts=[TextPart('总结：我已经完成所有操作。')])
        assert not deps.completed_steps
        assert any(
            isinstance(part, RetryPromptPart) and '尚未完成' in str(part.content)
            for message in messages
            for part in message.parts
        )
        assert info.model_settings is not None
        assert info.model_settings.get('tool_choice') == ToolOrOutput(['write_plan'])
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('开始学习', deps=deps)

    asyncio.run(exercise())
    assert calls == 2


def test_invalid_arguments_do_not_complete_a_step(tmp_path: Path) -> None:
    """Schema rejection leaves progress and the stored plan untouched, then a valid call works."""
    deps = LearningDeps()
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('write_plan', {'items': 'not-a-list'})])
        if calls == 2:
            assert not deps.completed_steps and not deps.completed_tools
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
            return ModelResponse(
                parts=[ToolCallPart('write_plan', {'items': [{'content': '学习', 'status': 'in_progress'}]})]
            )
        assert deps.completed_steps == ['write_plan']
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('开始学习', deps=deps)
        items = await SqlitePlanStore(str(tmp_path / 'plan.db')).get_items()
        assert len(items) == 1 and items[0].status is TaskStatus.in_progress

    asyncio.run(exercise())
    assert calls == 3


def test_input_guard_blocks_before_model_request(tmp_path: Path) -> None:
    """The configured guard runs inside the Agent, before any model callback."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError('The input guard must block before the model is called.')

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        deps = LearningDeps()
        async with agent:
            with pytest.raises(InputBlocked, match='禁用标记'):
                await agent.run('示例禁止', deps=deps)
        assert not deps.completed_tools

    asyncio.run(exercise())


def test_tool_guard_denial_is_not_counted_as_execution(tmp_path: Path) -> None:
    """An unapproved write returns a refusal to the model without touching the file."""
    deps = LearningDeps()
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart('write_file', {'path': 'forbidden.md', 'content': 'must not exist'})]
            )
        assert not deps.completed_tools
        assert any(
            isinstance(part, ToolReturnPart) and '只允许写 report.md' in str(part.content)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[TextPart('总结：写入已被护栏拒绝。')])

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond), guided=False)
        async with agent:
            await agent.run('尝试写 forbidden.md', deps=deps)
        assert not (tmp_path / 'forbidden.md').exists()
        assert not (tmp_path / 'report.md').exists()

    asyncio.run(exercise())


def test_final_plan_requires_completed_status(tmp_path: Path) -> None:
    """A successful write that leaves the task in progress must not complete the lesson."""
    deps = LearningDeps(completed_steps=[step.tool for step in LESSON_STEPS[:-2]])
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart('write_plan', {'items': [{'content': '学习', 'status': 'in_progress'}]})]
            )
        assert len(deps.completed_steps) == len(LESSON_STEPS) - 2
        assert any(
            isinstance(part, RetryPromptPart) and 'completed' in str(part.content)
            for message in messages
            for part in message.parts
        )
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        plan = SqlitePlanStore(str(tmp_path / 'plan.db'))
        await plan.set_items([PlanItem(content='原计划', status=TaskStatus.in_progress)])
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('完成最后的计划步骤', deps=deps)
        items = await plan.get_items()
        assert len(items) == 1 and items[0].content == '原计划'

    asyncio.run(exercise())


def test_output_retry_budget_covers_multiple_learning_steps(tmp_path: Path) -> None:
    """Local-model acknowledgements share a global budget even when successful tools separate them."""
    deps = LearningDeps()
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls <= 5 or 7 <= calls <= 11:
            return ModelResponse(parts=[TextPart('总结：收到，准备继续下一步。')])
        if calls == 6:
            return ModelResponse(
                parts=[ToolCallPart('write_plan', {'items': [{'content': '学习', 'status': 'in_progress'}]})]
            )
        if calls == 12:
            return ModelResponse(parts=[ToolCallPart('list_directory', {'path': '.'})])
        assert deps.completed_steps == ['write_plan', 'list_directory']
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('开始学习', deps=deps)

    asyncio.run(exercise())
    assert calls == 13


def test_delegation_cannot_select_an_unconfigured_cloud_model(tmp_path: Path) -> None:
    """The optional model argument is a configured menu key, not an arbitrary provider override."""
    deps = LearningDeps()
    calls = 0

    def reviewer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError('Rejected model selection must not start a child run.')

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        'delegate_task', {'agent_name': 'reviewer', 'task': '检查概念', 'model': 'openai:gpt-5'}
                    )
                ]
            )
        assert not deps.completed_tools and deps.successful_delegations == 0
        assert any(
            isinstance(part, RetryPromptPart) and 'none configured' in str(part.content)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[TextPart('总结：保持使用已配置的本地模型。')])

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(
            workspace=tmp_path, model=scripted_model(respond), reviewer_model=scripted_model(reviewer), guided=False
        )
        async with agent:
            await agent.run('检查概念', deps=deps)

    asyncio.run(exercise())
    assert calls == 2
