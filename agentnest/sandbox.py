"""High-level, backend-independent sandbox API."""

from __future__ import annotations

import posixpath
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from agentnest.exceptions import ExecutionTimeoutError, SandboxDestroyedError
from agentnest.models import ExecutionResult, ResourceLimits, SandboxConfig
from agentnest.runtime.base import RuntimeBackend


class Sandbox:
    """An isolated environment for executing untrusted agent workloads.

    Args:
        runtime: Container image (for example ``python:3.12-slim``).
        timeout: Maximum sandbox lifetime in seconds and default command timeout.
        environment: Environment variables inherited by all commands.
        workdir: Working directory inside the isolated ``/workspace`` mount.
        network_enabled: Permit outbound container networking. Disabled by default.
        memory: Docker-compatible memory limit, or a byte count.
        cpus: Fractional CPU quota.
        pids: Maximum number of processes in the sandbox.
        backend: Backend name or a custom :class:`RuntimeBackend` instance.
        read_only_root: Mount the container root filesystem read-only.
    """

    def __init__(
        self,
        runtime: str = "python:3.12-slim",
        timeout: float = 300,
        *,
        environment: Mapping[str, str] | None = None,
        workdir: str = "/workspace",
        network_enabled: bool = False,
        memory: str | int = "512m",
        cpus: float = 1.0,
        pids: int = 256,
        backend: str | RuntimeBackend = "docker",
        read_only_root: bool = True,
    ) -> None:
        self._config = SandboxConfig(
            image=runtime,
            timeout=timeout,
            environment=environment or {},
            workdir=self._normalize_workdir(workdir),
            network_enabled=network_enabled,
            limits=ResourceLimits(memory=memory, cpus=cpus, pids=pids),
            read_only_root=read_only_root,
        )
        self._backend = self._resolve_backend(backend)
        self._lock = threading.RLock()
        self._destroyed = False
        self._timer = threading.Timer(timeout, self.destroy)
        self._timer.daemon = True

        self._backend.create(self._config)
        self._deadline = time.monotonic() + timeout
        self._timer.start()

    def exec_python(
        self,
        code: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        """Execute Python source and return its captured result."""

        self._ensure_active()
        try:
            return self._backend.exec(
                ["python", "-c", code],
                display_command="python -c <code>",
                environment=environment,
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            )
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def exec_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        """Execute a POSIX shell script and return its captured result."""

        self._ensure_active()
        try:
            return self._backend.exec(
                ["sh", "-c", script],
                display_command=script,
                environment=environment,
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            )
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def write_file(self, path: str, content: str | bytes, *, encoding: str = "utf-8") -> None:
        """Write text or bytes to a relative workspace path."""

        self._ensure_active()
        payload = content.encode(encoding) if isinstance(content, str) else content
        self._backend.write_file(path, payload)

    def read_file(self, path: str, *, encoding: str | None = "utf-8") -> str | bytes:
        """Read a relative workspace path as text, or bytes when encoding is ``None``."""

        self._ensure_active()
        payload = self._backend.read_file(path)
        return payload if encoding is None else payload.decode(encoding)

    def upload_file(self, source: str | Path, destination: str | None = None) -> None:
        """Upload a local file into the workspace."""

        local_path = Path(source)
        target = destination or local_path.name
        self.write_file(target, local_path.read_bytes())

    def download_file(self, source: str, destination: str | Path) -> None:
        """Download a workspace file to an explicit local destination."""

        payload = self.read_file(source, encoding=None)
        assert isinstance(payload, bytes)
        local_path = Path(destination)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)

    def logs(self) -> str:
        """Return output accumulated by the sandbox backend."""

        return self._backend.logs()

    def destroy(self) -> None:
        """Idempotently destroy the sandbox and its temporary workspace."""

        with self._lock:
            if self._destroyed:
                return
            self._destroyed = True
            self._timer.cancel()
        self._backend.destroy()

    @property
    def destroyed(self) -> bool:
        """Whether this sandbox has been destroyed."""

        with self._lock:
            return self._destroyed

    def __enter__(self) -> Sandbox:
        self._ensure_active()
        return self

    def __exit__(self, *_: object) -> None:
        self.destroy()

    def _ensure_active(self) -> None:
        with self._lock:
            if self._destroyed:
                raise SandboxDestroyedError("the sandbox has been destroyed")

    def _effective_timeout(self, requested: float | None) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.destroy()
            raise SandboxDestroyedError("the sandbox lifetime has expired")
        if requested is not None and requested <= 0:
            raise ValueError("timeout must be positive")
        return min(requested, remaining) if requested is not None else remaining

    def _effective_workdir(self, requested: str | None) -> str:
        return self._normalize_workdir(requested or self._config.workdir)

    @staticmethod
    def _normalize_workdir(workdir: str) -> str:
        normalized = posixpath.normpath(workdir)
        if normalized != "/workspace" and not normalized.startswith("/workspace/"):
            raise ValueError("workdir must be /workspace or a directory beneath it")
        return normalized

    @staticmethod
    def _resolve_backend(backend: str | RuntimeBackend) -> RuntimeBackend:
        if isinstance(backend, RuntimeBackend):
            return backend
        if backend != "docker":
            raise ValueError(f"unknown runtime backend: {backend!r}")
        from agentnest.runtime.docker import DockerRuntime

        return DockerRuntime()
