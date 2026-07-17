"""High-level, backend-independent sandbox API."""

from __future__ import annotations

import json
import posixpath
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentnest.approvals import (
    Action,
    AllowAll,
    ApprovalHook,
    ApprovalRequest,
    require_approval,
)
from agentnest.artifacts import Artifact
from agentnest.capabilities import SnapshotBackend, StreamingBackend
from agentnest.events import EventObserver, EventType, SandboxEvent
from agentnest.exceptions import (
    ExecutionTimeoutError,
    SandboxDestroyedError,
    UnsupportedCapabilityError,
)
from agentnest.filesystem import normalize_workspace_path
from agentnest.models import (
    ExecutionChunk,
    ExecutionResult,
    ResourceLimits,
    SandboxConfig,
    SnapshotMetadata,
)
from agentnest.policy import NetworkMode, NetworkPolicy, SecurityPolicy
from agentnest.registry import registry
from agentnest.runtime.base import RuntimeBackend
from agentnest.secrets import Secret, redact, reveal_environment


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
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str = "/workspace",
        network_enabled: bool = False,
        memory: str | int = "512m",
        cpus: float = 1.0,
        pids: int = 256,
        gpus: int = 0,
        backend: str | RuntimeBackend = "docker",
        read_only_root: bool = True,
        security_policy: SecurityPolicy | None = None,
        observers: tuple[EventObserver, ...] = (),
        approval_hook: ApprovalHook | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex
        self._secrets = dict(environment or {})
        self._redaction_secrets = dict(environment or {})
        policy = security_policy or SecurityPolicy(
            network=NetworkPolicy.allowed() if network_enabled else NetworkPolicy.denied()
        )
        self._config = SandboxConfig(
            image=runtime,
            timeout=timeout,
            environment=reveal_environment(environment or {}),
            workdir=self._normalize_workdir(workdir),
            network_enabled=policy.network.mode is not NetworkMode.DENY,
            limits=ResourceLimits(memory=memory, cpus=cpus, pids=pids, gpus=gpus),
            read_only_root=read_only_root,
            security_policy=policy,
        )
        self._backend = self._resolve_backend(backend)
        self._lock = threading.RLock()
        self._destroyed = False
        self._observers = observers
        self._approval_hook = approval_hook or AllowAll()
        self._timer = threading.Timer(timeout, self.destroy)
        self._timer.daemon = True

        self._backend.create(self._config)
        self._deadline = time.monotonic() + timeout
        self._timer.start()
        self._emit(EventType.CREATED, image=runtime, backend=type(self._backend).__name__)

    def exec_python(
        self,
        code: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        """Execute Python source and return its captured result."""

        self._ensure_active()
        self._approve(Action.EXECUTE_PYTHON, code_bytes=len(code.encode()))
        self._remember_secrets(environment or {})
        self._emit(EventType.EXECUTION_STARTED, kind="python")
        try:
            result = self._backend.exec(
                ["python", "-c", code],
                display_command="python -c <code>",
                environment=reveal_environment(environment or {}),
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            )
            result = self._redact_result(result, environment or {})
            self._emit(
                EventType.EXECUTION_FINISHED,
                kind="python",
                exit_code=result.exit_code,
                duration=result.duration,
            )
            return result
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def exec(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
        display_command: str | None = None,
    ) -> ExecutionResult:
        """Execute an argument-vector command without invoking a shell."""

        self._ensure_active()
        if not command:
            raise ValueError("command must not be empty")
        self._approve(Action.EXECUTE, command=command)
        self._remember_secrets(environment or {})
        self._emit(EventType.EXECUTION_STARTED, kind="command")
        try:
            result = self._backend.exec(
                command,
                display_command=display_command or " ".join(command),
                environment=reveal_environment(environment or {}),
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            )
            result = self._redact_result(result, environment or {})
            self._emit(
                EventType.EXECUTION_FINISHED,
                kind="command",
                exit_code=result.exit_code,
                duration=result.duration,
            )
            return result
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def exec_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        """Execute a POSIX shell script and return its captured result."""

        self._ensure_active()
        self._approve(Action.EXECUTE_SHELL, script_bytes=len(script.encode()))
        self._remember_secrets(environment or {})
        self._emit(EventType.EXECUTION_STARTED, kind="shell")
        try:
            result = self._backend.exec(
                ["sh", "-c", script],
                display_command=script,
                environment=reveal_environment(environment or {}),
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            )
            result = self._redact_result(result, environment or {})
            self._emit(
                EventType.EXECUTION_FINISHED,
                kind="shell",
                exit_code=result.exit_code,
                duration=result.duration,
            )
            return result
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def stream_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> Iterator[ExecutionChunk]:
        """Yield stdout, stderr, and final status events as a shell script runs."""

        self._ensure_active()
        self._approve(Action.EXECUTE_SHELL, script_bytes=len(script.encode()), streaming=True)
        self._remember_secrets(environment or {})
        if not isinstance(self._backend, StreamingBackend):
            raise UnsupportedCapabilityError("this backend does not support streaming execution")
        self._emit(EventType.EXECUTION_STARTED, kind="shell", streaming=True)
        values = {**self._secrets, **(environment or {})}
        try:
            for chunk in self._backend.stream_exec(
                ["sh", "-c", script],
                display_command=script,
                environment=reveal_environment(environment or {}),
                workdir=self._effective_workdir(workdir),
                timeout=self._effective_timeout(timeout),
            ):
                yield replace(chunk, data=redact(chunk.data, values))
                if chunk.stream == "status":
                    self._emit(
                        EventType.EXECUTION_FINISHED,
                        kind="shell",
                        streaming=True,
                        exit_code=chunk.exit_code,
                    )
        except ExecutionTimeoutError:
            self.destroy()
            raise

    def write_file(self, path: str, content: str | bytes, *, encoding: str = "utf-8") -> None:
        """Write text or bytes to a relative workspace path."""

        self._ensure_active()
        path = normalize_workspace_path(path)
        self._approve(Action.WRITE_FILE, path=path, bytes=len(content))
        payload = content.encode(encoding) if isinstance(content, str) else content
        self._backend.write_file(path, payload)
        self._emit(EventType.FILE_WRITTEN, path=path, bytes=len(payload))

    def read_file(self, path: str, *, encoding: str | None = "utf-8") -> str | bytes:
        """Read a relative workspace path as text, or bytes when encoding is ``None``."""

        self._ensure_active()
        path = normalize_workspace_path(path)
        self._approve(Action.READ_FILE, path=path)
        payload = self._backend.read_file(path)
        if len(payload) > self._config.security_policy.max_file_read_bytes:
            raise ValueError("file exceeds security policy read limit")
        self._emit(EventType.FILE_READ, path=path, bytes=len(payload))
        return payload if encoding is None else payload.decode(encoding)

    def exec_json(
        self,
        code: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
    ) -> Any:
        """Execute Python and parse its stdout as JSON."""

        result = self.exec_python(code, timeout=timeout, environment=environment).check()
        return json.loads(result.stdout)

    def artifacts(self, pattern: str = "**/*") -> tuple[Artifact, ...]:
        """List regular workspace files with sizes and SHA-256 checksums."""

        if pattern.startswith("/") or ".." in pattern.split("/"):
            raise ValueError("artifact pattern must stay within the workspace")
        encoded_pattern = json.dumps(pattern)
        code = f"""
import hashlib, json
from pathlib import Path
root = Path('/workspace')
items = []
for path in sorted(root.glob({encoded_pattern})):
    if path.is_file() and not path.is_symlink():
        data = path.read_bytes()
        items.append({{
            'path': str(path.relative_to(root)),
            'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }})
print(json.dumps(items))
"""
        payload = self.exec_json(code)
        return tuple(Artifact(**item) for item in payload)

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

    def snapshot(self, destination: str | Path) -> SnapshotMetadata:
        """Create a portable filesystem snapshot when supported by the backend."""

        self._ensure_active()
        self._approve(Action.SNAPSHOT, destination=str(destination))
        if not isinstance(self._backend, SnapshotBackend):
            raise UnsupportedCapabilityError("this backend does not support snapshots")
        metadata = self._backend.snapshot(Path(destination))
        self._emit(
            EventType.SNAPSHOT_CREATED,
            path=str(metadata.path),
            size=metadata.size,
            sha256=metadata.sha256,
        )
        return metadata

    def restore(self, source: str | Path) -> None:
        """Replace workspace state from a portable filesystem snapshot."""

        self._ensure_active()
        self._approve(Action.RESTORE, source=str(source))
        if not isinstance(self._backend, SnapshotBackend):
            raise UnsupportedCapabilityError("this backend does not support snapshots")
        self._backend.restore(Path(source))
        self._emit(EventType.SNAPSHOT_RESTORED, path=str(source))

    def logs(self) -> str:
        """Return output accumulated by the sandbox backend."""

        return redact(self._backend.logs(), self._redaction_secrets)

    def destroy(self) -> None:
        """Idempotently destroy the sandbox and its temporary workspace."""

        with self._lock:
            if self._destroyed:
                return
            self._destroyed = True
            self._timer.cancel()
        self._backend.destroy()
        self._emit(EventType.DESTROYED)

    @property
    def destroyed(self) -> bool:
        """Whether this sandbox has been destroyed."""

        with self._lock:
            return self._destroyed

    @property
    def config(self) -> SandboxConfig:
        """Immutable effective configuration for this sandbox."""

        return self._config

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

    def _approve(self, action: Action, **details: Any) -> None:
        require_approval(self._approval_hook, ApprovalRequest(action, self.id, details))

    def _emit(self, event_type: EventType, **attributes: Any) -> None:
        event = SandboxEvent(event_type, self.id, attributes=attributes)
        for observer in self._observers:
            # Observability must never weaken lifecycle or cleanup guarantees.
            with suppress(Exception):
                observer.emit(event)

    def _redact_result(
        self, result: ExecutionResult, command_environment: Mapping[str, str | Secret]
    ) -> ExecutionResult:
        values = {**self._secrets, **command_environment}
        return replace(
            result,
            stdout=redact(result.stdout, values),
            stderr=redact(result.stderr, values),
        )

    def _remember_secrets(self, environment: Mapping[str, str | Secret]) -> None:
        for key, value in environment.items():
            if isinstance(value, Secret):
                self._redaction_secrets[f"{key}:{len(self._redaction_secrets)}"] = value

    @staticmethod
    def _resolve_backend(backend: str | RuntimeBackend) -> RuntimeBackend:
        if isinstance(backend, RuntimeBackend):
            return backend
        return registry.create(backend)
