"""本例的 Windows 原生适配器；不代表上游 LocalWorkspace/Shell 已支持 Windows.

文件工具使用虚拟 POSIX 根 /workspace；只允许访问配置目录以内的路径。
这是可信本地教学环境，不是抵抗并发文件系统篡改的操作系统沙箱。
Windows 命令工具仅执行 cmd.exe 内建 echo，不接受 POSIX 脚本或任意程序。
"""

import asyncio
import math
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import anyio

from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    SupportsFilesystem,
    SupportsRealpath,
    WorkspaceBackend,
    WorkspaceRef,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)
from pydantic_ai_harness import Shell

_RESERVED_NAME = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.IGNORECASE)
_ECHO = re.compile(r'echo [\w .-]{1,200}')


def _virtual_path(path: str) -> PurePosixPath:
    """兼容 Harness 经宿主 Path 生成的路径，边界仍使用虚拟 POSIX 根."""
    # RepoContext 使用宿主 Path；Windows 根路径经 Workspace.resolve 后可能多包一层 /workspace/。
    if path.startswith('/workspace/\\'):
        path = path[len('/workspace/') :]
    path = path.replace('\\', '/')
    virtual = PurePosixPath(path)
    if virtual.parts[:2] != ('/', 'workspace') or '..' in virtual.parts:
        raise ValueError('Paths must stay inside /workspace.')
    for part in virtual.parts[2:]:
        if (
            any(ord(char) < 32 or char in '\\<>:"|?*' for char in part)
            or part.endswith((' ', '.'))
            or _RESERVED_NAME.match(part)
        ):
            raise ValueError(f'Unsupported Windows path component: {part!r}')
    return virtual


class NativeWorkspaceBackend(WorkspaceBackend, SupportsFilesystem, SupportsRealpath):
    """将 /workspace 映射到宿主目录；文件后端不提供 POSIX shell 的 fallback."""

    def __init__(self, working_dir: Path):
        self.directory = working_dir.expanduser().absolute()
        self._resolved_root: Path | None = None
        self._ref = WorkspaceRef(provider='example-windows', id=str(self.directory))

    @property
    def ref(self) -> WorkspaceRef:
        """固定宿主目录标识，供快照恢复时核对."""
        return self._ref

    def _root(self) -> Path:
        root = self.directory.resolve()
        if not root.is_dir() or (self._resolved_root is not None and root != self._resolved_root):
            raise WorkspaceUnavailableError('The example workspace is missing or its root has changed.')
        self._resolved_root = root
        return root

    def _path(self, path: str, *, follow_symlinks: bool = True) -> Path:
        virtual = _virtual_path(path)
        root = self._root()
        target = root.joinpath(*virtual.parts[2:])
        resolved = target.resolve() if follow_symlinks or target == root else target.parent.resolve() / target.name
        if not resolved.is_relative_to(root):
            raise PermissionError('A path or symbolic link escapes the example workspace.')
        return resolved

    async def working_dir(self) -> str:
        """向模型和 Harness 返回稳定的虚拟工作目录."""
        await asyncio.to_thread(self._root)
        return '/workspace'

    async def realpath(self, path: str) -> str:
        """解析符号链接，并保持模型侧路径为 POSIX 格式."""

        def resolve() -> str:
            return str(PurePosixPath('/workspace') / self._path(path).relative_to(self._root()).as_posix())

        return await asyncio.to_thread(resolve)

    async def read_bytes(self, path: str) -> bytes:
        """读取普通文件；目录和设备不是可读取的教学资料."""

        def read() -> bytes:
            target = self._path(path)
            mode = target.stat().st_mode
            if stat.S_ISDIR(mode):
                raise IsADirectoryError(path)
            if not stat.S_ISREG(mode):
                raise OSError(f'Not a regular file: {path!r}')
            return target.read_bytes()

        return await asyncio.to_thread(read)

    async def write_bytes(self, path: str, data: bytes) -> None:
        """写入文件，缺失的父目录在工作区内创建."""

        def write() -> None:
            target = self._path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                raise IsADirectoryError(path)
            if target.exists() and not target.is_file():
                raise OSError(f'Not a regular file: {path!r}')
            target.write_bytes(data)

        await asyncio.to_thread(write)

    def _entry(self, path: str) -> FileEntry:
        virtual = _virtual_path(path)
        info = self._path(str(virtual)).stat()
        is_dir = stat.S_ISDIR(info.st_mode)
        return FileEntry(name=virtual.name, path=str(virtual), is_dir=is_dir, size=None if is_dir else info.st_size)

    async def stat(self, path: str) -> FileEntry:
        """返回虚拟路径下文件或目录的信息."""
        return await asyncio.to_thread(self._entry, path)

    async def list_dir(self, path: str) -> list[FileEntry]:
        """列出当前目录；每个条目仍需通过同一条路径边界检查."""

        def entries() -> list[FileEntry]:
            return [self._entry(str(_virtual_path(path) / child.name)) for child in sorted(self._path(path).iterdir())]

        return await asyncio.to_thread(entries)

    async def make_dir(self, path: str) -> None:
        """只在工作区内创建目录及父目录."""

        def make() -> None:
            self._path(path).mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(make)

    async def remove(self, path: str) -> None:
        """删除文件或目录；保留根目录，符号链接只删除链接本身."""

        def remove() -> None:
            target = self._path(path, follow_symlinks=False)
            root = self._root()
            if target == root or target in root.parents:
                raise ValueError('Cannot remove the workspace root or its ancestor.')
            if target.is_symlink():
                target.unlink()
            elif os.name == 'nt' and target.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                target.rmdir()  # junction 删除入口本身，不进入目标目录。
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

        await asyncio.to_thread(remove)

    async def exists(self, path: str) -> bool:
        """路径越界会报错；合法但不存在的路径返回 False."""
        return await asyncio.to_thread(lambda: self._path(path).exists())

    async def run_echo(self, command: str, timeout_seconds: float = 30) -> CommandResult:
        """只运行 Windows 内建 echo；取消或超时后终止并回收该进程."""
        if not _ECHO.fullmatch(command) or command[5:].strip().lower() in ('', 'on', 'off'):
            raise ValueError('Only echo followed by simple text is allowed; operators and expansion are forbidden.')
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError('timeout_seconds must be positive and finite.')
        if os.name != 'nt':
            raise RuntimeError('NativeShell is only used on Windows; use the built-in Shell on POSIX.')
        directory = await asyncio.to_thread(self._root)
        cmd = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'cmd.exe'
        environment = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if name in os.environ}
        starting = asyncio.create_task(
            asyncio.create_subprocess_exec(
                str(cmd),
                '/d',
                '/u',
                '/e:off',
                '/v:off',
                '/c',
                command,
                cwd=directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        )
        process: asyncio.subprocess.Process | None = None
        try:
            async with asyncio.timeout(timeout_seconds):
                running = await asyncio.shield(starting)
                process = running
                stdout, stderr = await running.communicate()
            assert running.returncode is not None
            return CommandResult(
                exit_code=running.returncode,
                stdout=stdout.decode('utf-16-le', errors='replace'),
                stderr=stderr.decode('utf-16-le', errors='replace'),
            )
        except TimeoutError as exc:
            raise WorkspaceTimeoutError(f'echo timed out after {timeout_seconds:g}s') from exc
        finally:
            # shield 使取消发生在启动阶段时，仍能取得进程句柄并完成清理。
            with anyio.CancelScope(shield=True):
                process = process or await starting
                if process.returncode is None:
                    process.kill()  # 只允许内建 echo，因此没有用户程序或后台子进程。
                await process.communicate()


@dataclass
class NativeWorkspace(AbstractCapability[object]):
    """为当前示例提供原生 Windows 文件工作区."""

    working_dir: Path
    id: str | None = field(default='local_workspace', kw_only=True)

    def __post_init__(self) -> None:
        self.working_dir = self.working_dir.expanduser().absolute()

    def get_workspace(self, ctx: RunContext[object], *, ref: WorkspaceRef | None) -> WorkspaceBackend | None:
        """历史中的 ref 只能恢复配置的同一个宿主目录."""
        backend = NativeWorkspaceBackend(self.working_dir)
        return backend if ref is None or ref == backend.ref else None


@dataclass
class NativeShell(AbstractCapability[object]):
    """仅在 Windows 教学中替代 Shell.run_command，不翻译 POSIX 脚本."""

    def get_toolset(self) -> FunctionToolset[object]:
        """命令和文件使用 ctx.workspace 中同一个后端、同一个宿主目录."""

        async def run_command(ctx: RunContext[object], command: str, timeout_seconds: float = 30) -> CommandResult:
            """Run echo with simple text in the Windows example workspace; no operators or expansion."""
            backend = ctx.workspace.backend
            if not isinstance(backend, NativeWorkspaceBackend):
                raise RuntimeError('NativeShell requires NativeWorkspace.')
            try:
                return await backend.run_echo(command, timeout_seconds)
            except ValueError as exc:
                raise ModelRetry(str(exc)) from exc

        return FunctionToolset[object](tools=[run_command])


def create_local_workspace(path: Path) -> AbstractCapability[object]:
    """Windows 使用本例适配器；POSIX 保持使用上游 LocalWorkspace."""
    return NativeWorkspace(path) if os.name == 'nt' else LocalWorkspace(path)


def create_shell() -> AbstractCapability[object]:
    """两种平台都只开放教学用的 run_command；Windows 的语法限制更严格."""
    if os.name == 'nt':
        return NativeShell()
    return Shell(tools=['run_command'], allowed_commands=['echo'], denied_operators=['>', '>>', '|', ';', '&&'])
