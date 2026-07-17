"""Shared data models used by the public API and runtime backends."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from agentnest.policy import SecurityPolicy


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Resource limits applied to a sandbox container."""

    memory: str | int = "512m"
    cpus: float = 1.0
    pids: int = 256
    gpus: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.memory, int) and self.memory <= 0:
            raise ValueError("memory must be positive")
        if isinstance(self.memory, str) and not self.memory.strip():
            raise ValueError("memory must not be empty")
        if self.cpus <= 0:
            raise ValueError("cpus must be positive")
        if self.pids <= 0:
            raise ValueError("pids must be positive")
        if self.gpus < 0:
            raise ValueError("gpus must be zero or positive")


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Backend-neutral sandbox creation settings."""

    image: str
    timeout: float
    environment: Mapping[str, str] = field(default_factory=dict)
    workdir: str = "/workspace"
    network_enabled: bool = False
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    read_only_root: bool = True
    security_policy: SecurityPolicy = field(default_factory=SecurityPolicy)

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise ValueError("image must not be empty")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.workdir != "/workspace" and not self.workdir.startswith("/workspace/"):
            raise ValueError("workdir must be /workspace or a directory beneath it")
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Captured output and status from one sandbox command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float

    @property
    def ok(self) -> bool:
        """Whether the process exited successfully."""

        return self.exit_code == 0

    def check(self) -> ExecutionResult:
        """Return this result or raise when the command failed."""

        if not self.ok:
            from agentnest.exceptions import ExecutionError

            detail = self.stderr.strip() or self.stdout.strip() or "no output"
            raise ExecutionError(f"command exited with status {self.exit_code}: {detail}")
        return self


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    """Description of a portable filesystem snapshot."""

    path: Path
    size: int
    sha256: str
    created_at: float


@dataclass(frozen=True, slots=True)
class ExecutionChunk:
    """One incremental stdout, stderr, or terminal status event."""

    stream: Literal["stdout", "stderr", "status"]
    data: str = ""
    timestamp: float = field(default_factory=time.time)
    exit_code: int | None = None
