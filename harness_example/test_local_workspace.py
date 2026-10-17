"""Test the example's native filesystem and Windows echo without model API calls."""

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness_example.local_workspace import (
    NativeShell,
    NativeWorkspace,
    NativeWorkspaceBackend,
    create_local_workspace,
    create_shell,
)
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.workspaces import Workspace, WorkspaceTimeoutError
from pydantic_ai_harness import FileSystem, Memory, RepoContext, Skills
from pydantic_ai_harness.memory import FileStore


def test_native_filesystem_round_trip_and_root_protection(tmp_path: Path) -> None:
    """Use the public Workspace facade with virtual paths and real host files."""

    async def exercise() -> None:
        backend = NativeWorkspaceBackend(tmp_path)
        workspace = Workspace(backend)
        assert await workspace.working_dir() == '/workspace'
        await workspace.write_bytes('notes/中文.txt', '学习'.encode())
        assert await workspace.read_bytes('notes/中文.txt') == '学习'.encode()
        assert (tmp_path / 'notes' / '中文.txt').read_text(encoding='utf-8') == '学习'
        assert await workspace.realpath('notes/中文.txt') == '/workspace/notes/中文.txt'
        entry = await workspace.stat('notes/中文.txt')
        assert entry.size == 6 and not entry.is_dir
        native_entry = await workspace.stat(r'\workspace\notes\中文.txt')
        assert native_entry.name == '中文.txt' and native_entry.path == '/workspace/notes/中文.txt'
        assert [item.path for item in await workspace.list_dir('notes')] == ['/workspace/notes/中文.txt']
        await workspace.make_dir('empty/subdir')
        assert await workspace.exists('empty/subdir')
        with pytest.raises(IsADirectoryError):
            await workspace.read_bytes('notes')
        with pytest.raises(FileNotFoundError):
            await workspace.read_bytes('missing.txt')
        for path in ('/workspace', '/', '/workspace/..'):
            with pytest.raises(ValueError):
                await backend.remove(path)
        await workspace.remove('notes')
        await workspace.remove('empty')
        assert tmp_path.exists() and not await workspace.exists('notes')

    asyncio.run(exercise())


@pytest.mark.parametrize(
    'path',
    [
        '/outside.txt',
        '/workspace/../outside.txt',
        '//server/share',
        '/workspace/a\\..\\outside.txt',
        '/workspace/\\outside.txt',
        '/workspace/\\\\server\\share',
        '/workspace/C:\\outside.txt',
        '/workspace/a:stream',
        '/workspace/NUL',
        '/workspace/com1.txt',
        '/workspace/name.',
        '/workspace/name ',
    ],
)
def test_windows_path_aliases_and_escapes_are_rejected(tmp_path: Path, path: str) -> None:
    """Reject NTFS aliases and host paths before any file is created."""

    async def exercise() -> None:
        with pytest.raises(ValueError):
            await NativeWorkspaceBackend(tmp_path).write_bytes(path, b'forbidden')
        assert not list(tmp_path.iterdir())

    asyncio.run(exercise())


@pytest.mark.parametrize('link_kind', ['symlink', 'junction'])
def test_symbolic_link_cannot_escape_but_can_be_removed(tmp_path: Path, link_kind: str) -> None:
    """An external target is never read, changed, or recursively deleted."""
    root = tmp_path / 'workspace'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'keep.txt').write_text('keep', encoding='utf-8')
    link = root / 'link'
    if link_kind == 'junction':
        if os.name != 'nt':
            pytest.skip('Directory junctions are Windows-specific.')
        cmd = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'cmd.exe'
        subprocess.run(
            f'"{cmd}" /d /c mklink /J "{link}" "{outside}"',
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            if error.winerror == 1314:
                pytest.skip('Windows has not granted symbolic-link creation permission.')
            raise

    async def exercise() -> None:
        backend = NativeWorkspaceBackend(root)
        with pytest.raises(PermissionError):
            await backend.read_bytes('/workspace/link/keep.txt')
        with pytest.raises(PermissionError):
            await backend.write_bytes('/workspace/link/keep.txt', b'changed')
        with pytest.raises(PermissionError):
            await backend.realpath('/workspace/link')
        await backend.remove('/workspace/link')
        assert not link.exists()
        assert (outside / 'keep.txt').read_text(encoding='utf-8') == 'keep'

    asyncio.run(exercise())


@pytest.mark.parametrize(
    'command',
    [
        'whoami',
        'echo ',
        'echo off',
        'echo %PATH%',
        'echo !PATH!',
        'echo a&whoami',
        'echo a|more',
        'echo a>b',
        'echo a^b',
        'echo a\nwhoami',
        'echo $(whoami)',
    ],
)
def test_echo_rejects_programs_operators_and_expansion(tmp_path: Path, command: str) -> None:
    """The teaching command cannot become a general Windows shell."""

    async def exercise() -> None:
        with pytest.raises(ValueError):
            await NativeWorkspaceBackend(tmp_path).run_echo(command)

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != 'nt', reason='This test executes the native Windows command interpreter.')
def test_native_agent_uses_one_workspace_for_files_memory_and_echo(tmp_path: Path) -> None:
    """Exercise the actual capability pipeline and cmd.exe on Windows."""
    assert isinstance(create_local_workspace(tmp_path), NativeWorkspace)
    assert isinstance(create_shell(), NativeShell)
    (tmp_path / 'AGENTS.md').write_text('Repository instruction marker.', encoding='utf-8')
    skill_dir = tmp_path / 'skills' / 'native-lesson'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'SKILL.md').write_text(
        '---\nname: native-lesson\ndescription: Native workspace lesson.\n---\nLoaded skill instruction marker.',
        encoding='utf-8',
    )
    calls = [
        ToolCallPart('load_capability', {'id': 'native-lesson'}),
        ToolCallPart('write_file', {'path': 'lesson.txt', 'content': 'local file'}),
        ToolCallPart('write_memory', {'content': 'persistent fact'}),
        ToolCallPart('run_command', {'command': 'echo harness-demo'}),
        ToolCallPart('read_file', {'path': 'lesson.txt'}),
    ]
    step = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal step
        assert info.instructions and 'Repository instruction marker.' in info.instructions
        assert not any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        if step > 0:
            assert 'Loaded skill instruction marker.' in info.instructions + str(messages)
        if step < len(calls):
            call = calls[step]
            step += 1
            return ModelResponse(parts=[call])
        assert any(
            isinstance(part, ToolReturnPart) and 'harness-demo' in str(part.content)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[TextPart('complete')])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        for part in respond(messages, info).parts:
            if isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args_as_dict()))}
            elif isinstance(part, TextPart):
                yield part.content

    async def exercise() -> None:
        agent = Agent(
            FunctionModel(respond, stream_function=stream),
            capabilities=[
                create_local_workspace(tmp_path),
                FileSystem(tools=['write_file', 'read_file'], content_hashes=False),
                Memory(FileStore('memory')),
                RepoContext(),
                Skills('skills'),
                create_shell(),
            ],
        )
        async with agent:
            result = await agent.run('Run the Windows learning tools.')
        assert result.output == 'complete'
        assert (tmp_path / 'lesson.txt').read_text(encoding='utf-8') == 'local file'
        assert 'persistent fact' in (tmp_path / 'memory' / 'main' / 'MEMORY.md').read_text(encoding='utf-8')

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != 'nt', reason='This test verifies native Windows subprocess cleanup.')
@pytest.mark.parametrize('cancel_during_startup', [False, True])
def test_echo_timeout_and_startup_cancellation_reap_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_during_startup: bool
) -> None:
    """A slow real child makes timeout/startup cancellation observable without racing echo."""
    create_process = asyncio.create_subprocess_exec
    processes: list[asyncio.subprocess.Process] = []

    async def exercise() -> None:
        spawned = asyncio.Event()
        release_handle = asyncio.Event()
        if not cancel_during_startup:
            release_handle.set()

        async def slow_process(
            *command: str, cwd: Path, env: dict[str, str], stdin: int, stdout: int, stderr: int, creationflags: int
        ) -> asyncio.subprocess.Process:
            assert cwd == tmp_path.resolve()
            assert command[-1] == 'echo harness-demo'
            process = await create_process(
                sys.executable,
                '-c',
                'import time; time.sleep(60)',
                cwd=cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
            )
            processes.append(process)
            spawned.set()
            await release_handle.wait()
            return process

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', slow_process)
        backend = NativeWorkspaceBackend(tmp_path)
        task = asyncio.create_task(backend.run_echo('echo harness-demo', 30 if cancel_during_startup else 0.05))
        if cancel_during_startup:
            await asyncio.wait_for(spawned.wait(), 5)
            task.cancel()
            release_handle.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        else:
            with pytest.raises(WorkspaceTimeoutError):
                await asyncio.wait_for(task, 5)
        assert processes and all(process.returncode is not None for process in processes)

    asyncio.run(exercise())
