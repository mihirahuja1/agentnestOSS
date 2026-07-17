"""In-memory backend used by unit tests."""

from __future__ import annotations

from collections.abc import Mapping

from agentnest.models import ExecutionResult, SandboxConfig
from agentnest.runtime.base import RuntimeBackend


class FakeRuntime(RuntimeBackend):
    def __init__(self) -> None:
        self.config: SandboxConfig | None = None
        self.commands: list[
            tuple[list[str], str, Mapping[str, str] | None, str | None, float | None]
        ] = []
        self.files: dict[str, bytes] = {}
        self.destroy_count = 0

    def create(self, config: SandboxConfig) -> None:
        self.config = config

    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        self.commands.append((command, display_command, environment, workdir, timeout))
        return ExecutionResult(display_command, 0, "ok\n", "", 0.01)

    def write_file(self, path: str, content: bytes) -> None:
        self.files[path] = content

    def read_file(self, path: str) -> bytes:
        return self.files[path]

    def logs(self) -> str:
        return "fake logs"

    def destroy(self) -> None:
        self.destroy_count += 1
