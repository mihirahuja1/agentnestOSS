"""Runtime backend discovery and registration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from importlib.metadata import entry_points

from agentnest.runtime.base import RuntimeBackend

BackendFactory = Callable[[], RuntimeBackend]


class RuntimeRegistry:
    """Thread-safe registry with Python entry-point discovery."""

    ENTRY_POINT_GROUP = "agentnest.backends"

    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}
        self._lock = threading.RLock()
        self._discovered = False

    def register(self, name: str, factory: BackendFactory, *, replace: bool = False) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("backend name must not be empty")
        with self._lock:
            if normalized in self._factories and not replace:
                raise ValueError(f"backend is already registered: {normalized!r}")
            self._factories[normalized] = factory

    def create(self, name: str) -> RuntimeBackend:
        self.discover()
        normalized = name.strip().lower()
        with self._lock:
            factory = self._factories.get(normalized)
        if factory is None:
            available = ", ".join(self.names()) or "none"
            raise ValueError(f"unknown runtime backend {name!r}; available: {available}")
        return factory()

    def names(self) -> tuple[str, ...]:
        self.discover()
        with self._lock:
            return tuple(sorted(self._factories))

    def discover(self) -> None:
        with self._lock:
            if self._discovered:
                return
            self._discovered = True
        for entry_point in entry_points(group=self.ENTRY_POINT_GROUP):
            self.register(entry_point.name, entry_point.load())


registry = RuntimeRegistry()


def _docker() -> RuntimeBackend:
    from agentnest.runtime.docker import DockerRuntime

    return DockerRuntime()


def _gvisor() -> RuntimeBackend:
    from agentnest.runtime.docker import DockerRuntime

    return DockerRuntime(runtime_name="runsc")


def _kata() -> RuntimeBackend:
    from agentnest.runtime.docker import DockerRuntime

    return DockerRuntime(runtime_name="kata-runtime")


def _kubernetes() -> RuntimeBackend:
    from agentnest.runtime.kubernetes import KubernetesRuntime

    return KubernetesRuntime()


registry.register("docker", _docker)
registry.register("gvisor", _gvisor)
registry.register("kata", _kata)
registry.register("kubernetes", _kubernetes)
