"""Optional backend capabilities that do not burden the core contract."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentnest.models import ExecutionChunk, SnapshotMetadata

if TYPE_CHECKING:
    from agentnest.runtime.base import RuntimeBackend


@runtime_checkable
class SnapshotBackend(Protocol):
    """Backend capable of exporting and restoring workspace state."""

    def snapshot(self, destination: Path) -> SnapshotMetadata: ...

    def restore(self, source: Path) -> None: ...


@runtime_checkable
class ForkableBackend(Protocol):
    """Backend capable of branching a running sandbox's state.

    A fork is an independent sandbox that starts from a copy of the parent's
    filesystem, letting an agent explore several continuations from one point --
    tree search, speculative fixes, parallel A/B attempts -- and discard the
    branches it does not keep.
    """

    def fork(self) -> RuntimeBackend: ...


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
