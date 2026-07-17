"""Bounded warm sandbox pools."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from agentnest.exceptions import PoolExhaustedError
from agentnest.sandbox import Sandbox


class SandboxPool:
    """Maintain a fixed number of reusable sandboxes.

    Instances that are destroyed or exceed ``max_uses`` are replaced before
    returning capacity to the pool.
    """

    def __init__(
        self,
        factory: Callable[[], Sandbox],
        *,
        size: int = 2,
        max_uses: int = 25,
    ) -> None:
        if size <= 0 or max_uses <= 0:
            raise ValueError("size and max_uses must be positive")
        self._factory = factory
        self._size = size
        self._max_uses = max_uses
        self._items: queue.Queue[tuple[Sandbox, int]] = queue.Queue(maxsize=size)
        self._closed = False
        self._lock = threading.Lock()
        for _ in range(size):
            self._items.put((factory(), 0))

    @contextmanager
    def acquire(self, timeout: float | None = None) -> Iterator[Sandbox]:
        """Borrow one sandbox and always return or replace it."""

        with self._lock:
            if self._closed:
                raise PoolExhaustedError("sandbox pool is closed")
        try:
            sandbox, uses = self._items.get(timeout=timeout)
        except queue.Empty as exc:
            raise PoolExhaustedError("timed out waiting for a sandbox") from exc
        try:
            yield sandbox
        finally:
            with self._lock:
                closed = self._closed
            uses += 1
            if closed or sandbox.destroyed or uses >= self._max_uses:
                sandbox.destroy()
                if not closed:
                    self._items.put((self._factory(), 0))
            else:
                self._items.put((sandbox, uses))

    def close(self) -> None:
        """Destroy all currently available sandboxes."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        while True:
            try:
                sandbox, _ = self._items.get_nowait()
            except queue.Empty:
                break
            sandbox.destroy()

    def __enter__(self) -> SandboxPool:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
