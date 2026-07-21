from __future__ import annotations

from pathlib import Path

import pytest

from agentnest import ExecutionTimeoutError, Sandbox, SandboxDestroyedError
from tests.fakes import FakeRuntime


def test_sandbox_creates_backend_and_executes() -> None:
    backend = FakeRuntime()
    with Sandbox(
        "python:test",
        timeout=10,
        environment={"BASE": "yes"},
        backend=backend,
    ) as sandbox:
        result = sandbox.exec_python(
            "print('hi')", environment={"ONE": "1"}, workdir="/workspace/src"
        )

    assert result.stdout == "ok\n"
    assert backend.config is not None
    assert backend.config.image == "python:test"
    command, display, environment, workdir, timeout = backend.commands[0]
    assert command == ["python", "-c", "print('hi')"]
    assert display == "python -c <code>"
    assert environment == {"ONE": "1"}
    assert workdir == "/workspace/src"
    assert timeout is not None and 0 < timeout <= 10
    assert backend.destroy_count == 1


def test_shell_files_logs_and_idempotent_destroy(tmp_path: Path) -> None:
    backend = FakeRuntime()
    sandbox = Sandbox(backend=backend)
    sandbox.write_file("main.py", "print('hello')")
    assert sandbox.read_file("main.py") == "print('hello')"
    assert sandbox.read_file("main.py", encoding=None) == b"print('hello')"

    source = tmp_path / "source.bin"
    source.write_bytes(b"binary")
    destination = tmp_path / "downloads" / "output.bin"
    sandbox.upload_file(source, "input.bin")
    sandbox.download_file("input.bin", destination)
    result = sandbox.exec_shell("echo hello")

    assert result.command == "echo hello"
    assert destination.read_bytes() == b"binary"
    assert sandbox.logs() == "fake logs"
    sandbox.destroy()
    sandbox.destroy()
    assert backend.destroy_count == 1


def test_operations_after_destroy_raise() -> None:
    sandbox = Sandbox(backend=FakeRuntime())
    sandbox.destroy()
    with pytest.raises(SandboxDestroyedError):
        sandbox.exec_shell("true")


@pytest.mark.parametrize("workdir", ["/", "/workspace-other", "workspace", "/tmp"])
def test_workdir_must_stay_in_workspace(workdir: str) -> None:
    with pytest.raises(ValueError, match="workdir"):
        Sandbox(workdir=workdir, backend=FakeRuntime())


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown runtime backend"):
        Sandbox(backend="magic")


def test_backend_timeout_leaves_sandbox_reusable() -> None:
    class TimingOutRuntime(FakeRuntime):
        def exec(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise ExecutionTimeoutError("timed out")

    backend = TimingOutRuntime()
    sandbox = Sandbox(backend=backend)
    with pytest.raises(ExecutionTimeoutError):
        sandbox.exec_shell("sleep forever")
    # A per-command timeout kills only that process; the sandbox stays usable so
    # an agent does not lose accumulated workspace state to one slow command.
    assert not sandbox.destroyed
    assert backend.destroy_count == 0
    sandbox.destroy()
