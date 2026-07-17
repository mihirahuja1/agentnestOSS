"""Optional backend capabilities that do not burden the core contract."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from agentnest.models import ExecutionChunk, SnapshotMetadata


@runtime_checkable
class SnapshotBackend(Protocol):
    """Backend capable of exporting and restoring workspace state."""

    def snapshot(self, destination: Path) -> SnapshotMetadata: ...

    def restore(self, source: Path) -> None: ...


@runtime_checkable
class StreamingBackend(Protocol):
    """Backend capable of incremental process output."""

    def stream_exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[ExecutionChunk]: ...
