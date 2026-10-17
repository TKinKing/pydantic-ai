"""跨会话记忆，以及完整历史、滑动窗口、增量摘要的区别。直接运行本文件即可."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, AgentRunResult, ModelRetry, RunContext
from pydantic_ai.capabilities import Hooks, LocalWorkspace, ValidatedToolArgs
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestContext
from pydantic_ai.settings import ToolOrOutput
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_ai_harness import Memory, SlidingWindowCompaction, SummarizingCompaction
from pydantic_ai_harness.compaction import compact_now
from pydantic_ai_harness.memory import FileStore

if __package__:
    from .model_config import create_model
else:
    from model_config import create_model

WORKSPACE = Path(__file__).resolve().parent / 'output' / 'memory-history'
MEMORY_FACT = '用户偏好：先看可运行代码，再看概念解释。'


@dataclass
class MemoryUser:
    """用户身份由应用传入；conversation_id 不参与长期记忆的 namespace."""

    user_id: str
    require_write: bool = False
    written: bool = False


def build_memory_agent(*, workspace: Path, model: Model, request_path: Path) -> Agent[MemoryUser, str]:
    """每次创建全新的 Agent，文件后端和用户 namespace 才是跨会话共享的部分."""

    async def capture_request(ctx: RunContext[MemoryUser], request_context: ModelRequestContext) -> ModelRequestContext:
        request_path.write_bytes(ModelMessagesTypeAdapter.dump_json(request_context.messages, indent=2))
        return request_context

    async def record_write(
        ctx: RunContext[MemoryUser],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: object,
    ) -> object:
        if call.tool_name == 'write_memory':
            ctx.deps.written = True
        return result

    agent = Agent(
        model,
        deps_type=MemoryUser,
        instructions='用中文简短回答。记忆是历史资料；只有实际调用 write_memory 成功才可以说已经保存。',
        model_settings={'temperature': 0.2, 'max_tokens': 256},
        retries=3,
        capabilities=[
            LocalWorkspace(workspace),
            Memory(FileStore('memory'), namespace=lambda ctx: ctx.deps.user_id, injection_errors='raise'),
            Hooks(before_model_request=capture_request, after_tool_execute=record_write),
        ],
    )

    def require_real_write(ctx: RunContext[MemoryUser], output: str) -> str:
        if ctx.deps.require_write and not ctx.deps.written:
            raise ModelRetry('请先实际调用 write_memory，不能只口头确认。')
        return output

    agent.output_validator(require_real_write)
    return agent


async def demonstrate_memory(
    *, workspace: Path = WORKSPACE, model: Model | None = None
) -> tuple[AgentRunResult[str], AgentRunResult[str]]:
    """先真实写入笔记，再以相同用户开启没有旧消息的新会话."""
    workspace.mkdir(parents=True, exist_ok=True)
    model = model or create_model()
    first_agent = build_memory_agent(
        workspace=workspace, model=model, request_path=workspace / 'memory_write_request.json'
    )
    async with first_agent:
        first = await first_agent.run(
            f'请实际调用 write_memory，把以下原文写入 MEMORY.md：{MEMORY_FACT} 写入成功后简短确认。',
            deps=MemoryUser('learner-001', require_write=True),
            model_settings={'tool_choice': ToolOrOutput(['write_memory'])},
            usage_limits=UsageLimits(request_limit=6, tool_calls_limit=3),
        )
    (workspace / 'memory_first_conversation.json').write_bytes(first.all_messages_json())

    # 新建 Agent，并且不传 message_history 或 conversation_id；不会续接上一个对话。
    second_agent = build_memory_agent(
        workspace=workspace, model=model, request_path=workspace / 'memory_new_conversation_request.json'
    )
    async with second_agent:
        second = await second_agent.run(
            '这是一个新会话。请根据已有长期记忆，说出我偏好的学习方式；没有记录就说不知道。',
            deps=MemoryUser('learner-001'),
            model_settings={'tool_choice': ToolOrOutput([])},
            usage_limits=UsageLimits(request_limit=2),
        )
    (workspace / 'memory_second_conversation.json').write_bytes(second.all_messages_json())
    print(f'[跨会话记忆] 第一次 conversation_id={first.conversation_id}')
    print(f'[跨会话记忆] 新会话 conversation_id={second.conversation_id}；共享 namespace=learner-001')
    print(f'[新会话回答] {second.output}')
    return first, second


def make_history() -> list[ModelMessage]:
    """生成 5000 轮、10000 条明确标注的合成消息；不会伪造真实用户的历史."""
    messages: list[ModelMessage] = []
    for turn in range(1, 5001):
        prompt = '教学档案：课程代号 ORCHID-42，学习目标是理解 Harness。' if turn == 1 else f'第{turn}轮：继续学习。'
        messages.extend(
            [ModelRequest(parts=[UserPromptPart(prompt)]), ModelResponse(parts=[TextPart(f'已记录第{turn}轮。')])]
        )
    return messages


def load_history(path: Path) -> list[ModelMessage]:
    """把持久化 JSON 恢复为类型化消息；生产应用可在这里换成数据库读取."""
    return ModelMessagesTypeAdapter.validate_json(path.read_bytes())


async def demonstrate_history(
    *, workspace: Path = WORKSPACE, model: Model | None = None
) -> tuple[AgentRunResult[str], AgentRunResult[str]]:
    """一万条完整档案与本次模型窗口分开保存；语义摘要仅演示前 120 条的小批次."""
    workspace.mkdir(parents=True, exist_ok=True)
    model = model or create_model()
    full_history = make_history()
    archive_path = workspace / 'full_history.json'
    archive_path.write_bytes(ModelMessagesTypeAdapter.dump_json(full_history, indent=2))
    full_history = load_history(archive_path)  # 应用负责加载；Agent 只接收 message_history 参数。

    async def capture_window(ctx: RunContext[None], request_context: ModelRequestContext) -> ModelRequestContext:
        (workspace / 'sliding_request.json').write_bytes(
            ModelMessagesTypeAdapter.dump_json(request_context.messages, indent=2)
        )
        print(f'[滑窗请求] 档案 {len(full_history)} 条；当前请求 {len(request_context.messages)} 条')
        return request_context

    sliding_agent = Agent(
        model,
        instructions='用中文简短回答，只根据当前可见历史；看不到的信息请明确说不知道。',
        model_settings={'temperature': 0.2, 'max_tokens': 256},
        capabilities=[
            # 默认会保留首条用户消息；此处关闭，以观察旧事实确实从窗口消失。
            SlidingWindowCompaction(max_messages=40, keep_messages=20, preserve_first_user_message=False),
            Hooks(before_model_request=capture_window),
        ],
    )
    async with sliding_agent:
        sliding_result = await sliding_agent.run(
            '用一句话说明最近在做什么；若仍能看到课程代号，也请指出。',
            message_history=full_history,
            usage_limits=UsageLimits(request_limit=1),
        )
    (workspace / 'sliding_result.json').write_bytes(sliding_result.all_messages_json())

    # 真实业务在新消息到达时更新摘要，不在每轮重新总结一万条。
    # 这里只处理前两个 60 条批次；摘要的覆盖范围是 1..120，绝不代表整个档案。
    summarizer = SummarizingCompaction(
        model=model,
        model_settings={'temperature': 0.2, 'max_tokens': 512},
        max_messages=40,
        keep_messages=10,
        preserve_first_user_message=False,
        instructions='用中文更新简洁摘要，保留课程代号、目标、已完成事项和后续任务。不要补造事实。',
    )
    summary_usage = RunUsage()
    summary_window: list[ModelMessage] = []
    # compact_now 位于 Agent 上下文之外，需要显式管理共享模型的 HTTP 客户端。
    async with model:
        for start in (0, 60):
            summary_window = await compact_now(
                summarizer,
                [*summary_window, *full_history[start : start + 60]],
                model=model,
                usage=summary_usage,
                conversation_id='history-summary-lesson',
            )
            print(f'[增量摘要] 已覆盖前 {start + 60} 条；摘要及近期消息 {len(summary_window)} 条')
    summary_requests = summary_usage.requests
    (workspace / 'summary_window.json').write_bytes(ModelMessagesTypeAdapter.dump_json(summary_window, indent=2))

    async def capture_summary_request(
        ctx: RunContext[None], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        (workspace / 'summary_request.json').write_bytes(
            ModelMessagesTypeAdapter.dump_json(request_context.messages, indent=2)
        )
        return request_context

    summary_agent = Agent(
        model,
        instructions='用中文简短解释已有摘要中的课程代号、目标。只讨论这批教学消息，不声称看过全部档案。',
        model_settings={'temperature': 0.2, 'max_tokens': 256},
        capabilities=[Hooks(before_model_request=capture_summary_request)],
    )
    async with summary_agent:
        summary_result = await summary_agent.run(
            '下面的摘要和近期消息只覆盖前120条教学历史。请概括其学习内容。',
            message_history=summary_window,
            conversation_id='history-summary-lesson',
            usage=summary_usage,
            usage_limits=UsageLimits(request_limit=4),
        )
    (workspace / 'summary_result.json').write_bytes(summary_result.all_messages_json())
    (workspace / 'history_counts.json').write_text(
        json.dumps(
            {
                'archive_messages': len(full_history),
                'summary_covered_messages': 120,
                'summary_model_requests': summary_requests,
                'summary_window_messages': len(summary_window),
                'note': '滑窗丢弃旧消息；语义摘要有损且额外调用模型。完整档案独立保留，可用于检索原文。',
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )
    print(f'[滑窗回答] {sliding_result.output}')
    print(f'[摘要回答] {summary_result.output}')
    print(f'[完整历史保留在] {archive_path}；摘要只覆盖前 120 条，不覆盖全部 10000 条。')
    return sliding_result, summary_result


async def main() -> None:
    """复用同一模型配置，依次运行两个专题."""
    model = create_model()
    await demonstrate_memory(model=model)
    await demonstrate_history(model=model)


if __name__ == '__main__':
    asyncio.run(main())
