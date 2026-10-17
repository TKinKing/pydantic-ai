"""Verify the complete example through real Agent/Harness pipelines without model API calls."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from itertools import groupby
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from harness_example.main import (
    LESSON_STEPS,
    LearningDeps,
    build_agent,
    make_offline_model,
    make_reviewer_model,
    prepare_workspace,
    run_example,
)
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


def learning_plan() -> list[PlanItem]:
    """A parent and three independently trackable pieces of work, with stable example ids."""
    return [
        PlanItem(id='study', content='学习 Harness 并输出报告'),
        PlanItem(id='research', parent_id='study', content='阅读并检索资料'),
        PlanItem(id='practice', parent_id='study', content='实践工具并检查概念'),
        PlanItem(id='report', parent_id='study', content='保存记忆并写报告'),
    ]


def plan_arguments() -> dict[str, object]:
    """Serialize the proposed plan as a real model tool call."""
    return {'items': [item.model_dump(mode='json') for item in learning_plan()]}


def test_offline_walkthrough_and_snapshot_continuation(tmp_path: Path) -> None:
    """Run the tools, persist their artifacts and continue without repeating side effects."""

    async def exercise() -> None:
        result = await run_example(workspace=tmp_path, model=make_offline_model(), reviewer_model=make_reviewer_model())
        evidence = json.loads((tmp_path / 'coverage.json').read_text(encoding='utf-8'))
        assert len(evidence['completed_steps']) == len(LESSON_STEPS)
        assert evidence['completed_tools'].count('write_file') == 1
        assert evidence['completed_tools'].count('write_memory') == 1
        assert evidence['successful_delegations'] == 1
        assert evidence['context_events'] >= len(LESSON_STEPS)
        assert evidence['continued_from_snapshot']
        assert 'Agent 负责循环' in (tmp_path / 'report.md').read_text(encoding='utf-8')
        memory = list((tmp_path / 'memory').rglob('MEMORY.md'))
        assert len(memory) == 1
        assert 'Harness 通过 capabilities' in memory[0].read_text(encoding='utf-8')
        items = await SqlitePlanStore(str(tmp_path / 'plan.db')).get_items()
        by_id = {item.id: item for item in items}
        assert set(by_id) == {'study', 'research', 'practice', 'report'}
        assert all(item.status is TaskStatus.completed for item in items)
        assert by_id['study'].parent_id is None
        assert all(by_id[name].parent_id == 'study' for name in ('research', 'practice', 'report'))
        assert by_id['practice'].depends_on == ['research']
        assert by_id['report'].depends_on == ['practice']
        archived_plan = TypeAdapter(list[PlanItem]).validate_json((tmp_path / 'plan.json').read_bytes())
        assert archived_plan == items

        history = json.loads((tmp_path / 'plan_history.json').read_text(encoding='utf-8'))
        states = [{item['id']: item for item in entry['items']} for entry in history]
        assert [status for status, _ in groupby(state['research']['status'] for state in states)] == [
            'pending',
            'in_progress',
            'completed',
        ]
        for task_id in ('practice', 'report'):
            assert [status for status, _ in groupby(state[task_id]['status'] for state in states)] == [
                'pending',
                'blocked',
                'pending',
                'in_progress',
                'completed',
            ]
        available = [state for entry, state in zip(history, states) if entry['tool'] == 'get_available_tasks']
        assert len(available) == 3
        assert available[0]['practice']['status'] == available[0]['report']['status'] == 'blocked'
        assert available[1]['practice']['status'] == 'pending' and available[1]['report']['status'] == 'blocked'
        assert available[2]['report']['status'] == 'pending'
        report_finished = next(state for state in states if state['report']['status'] == 'completed')
        assert report_finished['study']['status'] == 'pending'  # Child completion does not complete its parent.
        parent_finished = next(index for index, state in enumerate(states) if state['study']['status'] == 'completed')
        assert history[parent_finished]['tool'] == 'update_task_status'
        assert states[parent_finished - 1]['study']['status'] == 'pending'
        assert all(
            states[parent_finished - 1][name]['status'] == 'completed' for name in ('research', 'practice', 'report')
        )
        assert (tmp_path / 'tools.json').exists()
        assert (tmp_path / 'continued_messages.json').exists()
        for history_path in ('messages.json', 'continued_messages.json'):
            persisted = (tmp_path / history_path).read_text(encoding='utf-8')
            assert '[harness-learning-step]' not in persisted
            assert '<plan-reminder>' not in persisted

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
        available_replies = [str(part.content) for part in returns if part.tool_name == 'get_available_tasks']
        for available_id, waiting_ids in [
            ('research', ('practice', 'report')),
            ('practice', ('research', 'report')),
            ('report', ('research', 'practice')),
        ]:
            assert any(
                f'[{available_id}]' in reply and all(f'[{waiting_id}]' not in reply for waiting_id in waiting_ids)
                for reply in available_replies
            )
        assert any(part.tool_name == 'read_plan' and 'hierarchical view' in str(part.content) for part in returns)
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
            return ModelResponse(parts=[ToolCallPart('write_plan', plan_arguments())])
        assert deps.completed_steps == ['write_plan']
        reminders = [
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart) and '<plan-reminder>' in str(part.content)
        ]
        assert reminders and all(item.content in reminders[-1] for item in learning_plan())
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('开始学习', deps=deps)
        items = await SqlitePlanStore(str(tmp_path / 'plan.db')).get_items()
        assert items == learning_plan()

    asyncio.run(exercise())
    assert calls == 3


@pytest.mark.parametrize(
    'scenario', ['single_task', 'wrong_dependency', 'missing_prerequisite', 'premature_completion']
)
def test_invalid_decomposition_or_transition_cannot_advance(tmp_path: Path, scenario: str) -> None:
    """Reject a fake decomposition, the wrong prerequisite, or claiming work done before it starts."""
    original = learning_plan()
    completed: list[str] = []
    if scenario == 'single_task':
        original = []
        call = ToolCallPart('write_plan', {'items': [{'id': 'study', 'content': '全部工作', 'status': 'pending'}]})
    elif scenario == 'wrong_dependency':
        completed = ['write_plan']
        call = ToolCallPart('set_dependency', {'task_id': 'practice', 'depends_on_id': 'report'})
    elif scenario == 'missing_prerequisite':
        completed = ['write_plan']
        original = [original[0], original[2]]
        call = ToolCallPart('set_dependency', {'task_id': 'practice', 'depends_on_id': 'research'})
    else:
        completed = ['write_plan', 'set_dependency', 'set_dependency', 'get_available_tasks']
        original[2].depends_on = ['research']
        original[2].status = TaskStatus.blocked
        original[3].depends_on = ['practice']
        original[3].status = TaskStatus.blocked
        call = ToolCallPart('update_task_status', {'task_id': 'research', 'status': 'completed'})
    deps = LearningDeps(completed_steps=completed.copy())
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[call])
        assert deps.completed_steps == completed and not deps.completed_tools
        assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        plan = SqlitePlanStore(str(tmp_path / 'plan.db'))
        await plan.set_items(original)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('继续拆解和执行任务', deps=deps)
        assert await plan.get_items() == original

    asyncio.run(exercise())
    assert calls == 2


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


@pytest.mark.parametrize('unfinished_child', [False, True])
def test_final_plan_requires_completed_status(tmp_path: Path, unfinished_child: bool) -> None:
    """Complete the parent explicitly, and only after all its children are done."""
    deps = LearningDeps(completed_steps=[step.tool for step in LESSON_STEPS[:-2]])
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        'update_task_status',
                        {'task_id': 'study', 'status': 'completed' if unfinished_child else 'in_progress'},
                    )
                ]
            )
        assert len(deps.completed_steps) == len(LESSON_STEPS) - 2
        assert not deps.completed_tools
        assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        raise ProbeFinished

    async def exercise() -> None:
        prepare_workspace(tmp_path)
        plan = SqlitePlanStore(str(tmp_path / 'plan.db'))
        original = learning_plan()
        for item in original[1:]:
            item.status = TaskStatus.completed
        if unfinished_child:
            original[-1].status = TaskStatus.in_progress
        await plan.set_items(original)
        agent, _ = build_agent(workspace=tmp_path, model=scripted_model(respond))
        async with agent:
            with pytest.raises(ProbeFinished):
                await agent.run('完成父任务', deps=deps)
        assert await plan.get_items() == original

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
            return ModelResponse(parts=[ToolCallPart('write_plan', plan_arguments())])
        if calls == 12:
            return ModelResponse(
                parts=[ToolCallPart('set_dependency', {'task_id': 'practice', 'depends_on_id': 'research'})]
            )
        assert deps.completed_steps == ['write_plan', 'set_dependency']
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
