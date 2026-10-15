"""Verify the interactive tool flow without connecting to Ollama."""

import asyncio
import json

import pytest

from pydantic_agent_example.main import LearningDeps, build_agent, run_interactive
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
from pydantic_ai.models.function import AgentInfo, FunctionModel


@pytest.mark.parametrize('json_args', [False, True], ids=['dict-args', 'json-args'])
def test_interactive_pause_and_resume(
    json_args: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Carry the user's answer across runs and reject premature final output."""
    original_question = 'Agent 是怎么调用工具的？'
    followup_question = '你希望看业务例子还是内部执行顺序？'
    user_answer = '内部执行顺序，最好有一个小例子。'
    final_answer = '模型提出工具调用，框架执行 Python 函数，再将结果交回模型。'
    responses = iter(
        [
            ModelResponse(parts=[TextPart('跳过工具直接回答。')]),
            ModelResponse(parts=[ToolCallPart('explain_concept', {'concept': '工具'}, 'concept-call')]),
            ModelResponse(parts=[TextPart('查询概念后直接回答，不追问。')]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        'ask_learner',
                        json.dumps({'question': followup_question}) if json_args else {'question': followup_question},
                        'question-call',
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(final_answer)]),
        ]
    )
    model_requests: list[list[ModelMessage]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert {tool.name for tool in info.function_tools} == {'explain_concept', 'ask_learner'}
        model_requests.append(list(messages))
        return next(responses)

    answers = iter([' ', original_question, '', user_answer])
    prompts: list[str] = []

    def read_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr('builtins.input', read_input)
    deps = LearningDeps(learner='测试学习者')

    async def exercise() -> AgentRunResult[str | DeferredToolRequests]:
        agent = build_agent()
        with agent.override(model=FunctionModel(respond)):
            async with agent:
                return await run_interactive(agent, deps)

    result = asyncio.run(exercise())

    assert result.output == final_answer
    assert deps.concept_explained
    assert deps.answers_received == 1
    assert len(model_requests) == result.usage.requests == 5
    # 延迟调用由外部提供结果，不算一次成功执行的本地工具调用。
    assert result.usage.tool_calls == 1

    resumed_parts = [
        part for message in model_requests[-1] if isinstance(message, ModelRequest) for part in message.parts
    ]
    assert [part.content for part in resumed_parts if isinstance(part, UserPromptPart)] == [original_question]
    tool_returns = [part for part in resumed_parts if isinstance(part, ToolReturnPart)]
    assert [part.tool_call_id for part in tool_returns] == ['concept-call', 'question-call']
    assert isinstance(tool_returns[0].content, str) and tool_returns[0].content
    assert tool_returns[1].content == user_answer
    retry_messages = [part.content for part in resumed_parts if isinstance(part, RetryPromptPart)]
    assert len(retry_messages) == 2
    assert 'explain_concept' in str(retry_messages[0])
    assert 'ask_learner' in str(retry_messages[1])
    assert result.conversation.deferred_tool_requests is None
    assert len({message.run_id for message in result.all_messages() if message.run_id is not None}) == 2

    output = capsys.readouterr().out
    assert output.count('[tool] explain_concept(') == 1
    assert output.count('[deferred tool] ask_learner(') == 1
    assert output.count('[cap.before_run]') == 2
    assert output.count('[cap.after_run]') == 2
    assert output.count('[cap.wrap_run] 进入') == 2
    assert output.count('[cap.wrap_run] 退出') == 2
    assert '暂停，等待用户回答' in output
    assert '已生成最终答案' in output
    assert final_answer in output
    assert output.count('输入不能为空，请重新输入。') == 2
    assert len(prompts) == 4
    assert prompts[2] == prompts[3]
    assert followup_question in prompts[2]
