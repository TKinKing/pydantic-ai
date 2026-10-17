"""离线模型只提供决策，验证真实工具执行、子 Agent 编排与后台消息交付."""

import asyncio
import json

import pytest

from harness_example.main import Lesson, background, code_mode, run_lesson, workflow
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.test import TestModel


def test_code_mode_executes_nested_host_tools() -> None:
    """沙箱脚本实际调用两个宿主工具并计算结果."""
    result = asyncio.run(run_lesson('code-mode', offline=True))
    returns = [
        part
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == 'run_code'
    ]
    assert len(returns) == 1
    assert json.loads(returns[0].model_response_str()) == {'quantities': [7, 11], 'total': 18}
    assert result.usage.requests == 2


def test_workflow_runs_two_isolated_child_agents() -> None:
    """编排脚本将首个子 Agent 的结果交给第二个."""
    result = asyncio.run(run_lesson('workflow', offline=True))
    assert (
        'reviewer: Check this explanation and add where tools run: explainer: Explain the Agent loop' in result.output
    )
    # 主 Agent 两次请求，加上两个子 Agent 各一次；用量由 DynamicWorkflow 汇总。
    assert result.usage.requests == 4


def test_background_result_arrives_after_independent_work() -> None:
    """后台结果在独立任务完成后进入消息历史."""
    result = asyncio.run(run_lesson('background', offline=True))
    assert 'independent-step-complete' in result.output
    assert 'background-complete' in result.output
    parts = [part for message in result.all_messages() if isinstance(message, ModelRequest) for part in message.parts]
    independent_index = next(
        index
        for index, part in enumerate(parts)
        if isinstance(part, ToolReturnPart) and part.tool_name == 'independent_step'
    )
    completed_index = next(
        index
        for index, part in enumerate(parts)
        if isinstance(part, UserPromptPart) and isinstance(part.content, str) and 'background-complete' in part.content
    )
    assert completed_index > independent_index


@pytest.mark.parametrize('lesson', ['code-mode', 'workflow', 'background'])
def test_completion_requires_real_execution(lesson: Lesson) -> None:
    """模型只宣称完成、没有执行能力时，实验必须报错."""
    model = TestModel(call_tools=[], custom_output_text='All done!')
    if lesson == 'code-mode':
        run = code_mode(model)
    elif lesson == 'workflow':
        run = workflow(model, offline=True)
    else:
        run = background(model)
    with pytest.raises(RuntimeError, match='实验未完成'):
        asyncio.run(run)
