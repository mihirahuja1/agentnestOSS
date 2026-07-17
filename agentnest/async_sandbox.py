"""Async facade for applications with an event loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from agentnest.models import ExecutionChunk, ExecutionResult, SnapshotMetadata
from agentnest.sandbox import Sandbox
from agentnest.secrets import Secret


class AsyncSandbox:
    """Non-blocking wrapper around :class:`Sandbox`.

    Creation is asynchronous through :meth:`create`, ensuring Docker image
    pulls never block an application's event loop.
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @classmethod
    async def create(cls, *args: Any, **kwargs: Any) -> AsyncSandbox:
        sandbox = await asyncio.to_thread(Sandbox, *args, **kwargs)
        return cls(sandbox)

    @property
    def id(self) -> str:
        return self._sandbox.id

    @property
    def destroyed(self) -> bool:
        return self._sandbox.destroyed

    async def exec_python(
        self,
        code: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        return await asyncio.to_thread(
            self._sandbox.exec_python,
            code,
            timeout=timeout,
            environment=environment,
            workdir=workdir,
        )

    async def exec_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> ExecutionResult:
        return await asyncio.to_thread(
            self._sandbox.exec_shell,
            script,
            timeout=timeout,
            environment=environment,
            workdir=workdir,
        )

    async def stream_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        environment: Mapping[str, str | Secret] | None = None,
        workdir: str | None = None,
    ) -> AsyncIterator[ExecutionChunk]:
        """Bridge incremental backend events into the current event loop."""

        loop = asyncio.get_running_loop()
        events: asyncio.Queue[ExecutionChunk | BaseException | None] = asyncio.Queue()

        def produce() -> None:
            try:
                for chunk in self._sandbox.stream_shell(
                    script, timeout=timeout, environment=environment, workdir=workdir
                ):
                    loop.call_soon_threadsafe(events.put_nowait, chunk)
            except BaseException as exc:
                loop.call_soon_threadsafe(events.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(events.put_nowait, None)

        producer_task = asyncio.create_task(asyncio.to_thread(produce))
        while True:
            event = await events.get()
            if event is None:
                break
            if isinstance(event, BaseException):
                raise event
            yield event
        await producer_task

    async def write_file(self, path: str, content: str | bytes) -> None:
        await asyncio.to_thread(self._sandbox.write_file, path, content)

    async def read_file(self, path: str, *, encoding: str | None = "utf-8") -> str | bytes:
        return await asyncio.to_thread(self._sandbox.read_file, path, encoding=encoding)

    async def snapshot(self, destination: str | Path) -> SnapshotMetadata:
        return await asyncio.to_thread(self._sandbox.snapshot, destination)

    async def restore(self, source: str | Path) -> None:
        await asyncio.to_thread(self._sandbox.restore, source)

    async def logs(self) -> str:
        return await asyncio.to_thread(self._sandbox.logs)

    async def destroy(self) -> None:
        await asyncio.to_thread(self._sandbox.destroy)

    async def __aenter__(self) -> AsyncSandbox:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()
