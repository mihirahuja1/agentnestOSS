"""Backend contract for isolated execution runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from agentnest.models import ExecutionResult, SandboxConfig


class RuntimeBackend(ABC):
    """Abstract lifecycle and I/O contract implemented by every runtime.

    A backend instance represents one sandbox. Backends may use containers,
    micro-VMs, remote workers, or another isolation mechanism without changing
    the higher-level :class:`agentnest.Sandbox` API.
    """

    @abstractmethod
    def create(self, config: SandboxConfig) -> None:
        """Create and start the isolated environment."""

    @abstractmethod
    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute a command and capture its output."""

    @abstractmethod
    def write_file(self, path: str, content: bytes) -> None:
        """Write bytes into the sandbox workspace."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read bytes from the sandbox workspace."""

    @abstractmethod
    def logs(self) -> str:
        """Return accumulated sandbox execution logs."""

    @abstractmethod
    def destroy(self) -> None:
        """Permanently stop and remove the isolated environment."""
