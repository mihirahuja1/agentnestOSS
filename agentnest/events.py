"""Structured lifecycle events and lightweight observer integrations."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from importlib import import_module
from typing import Any, Protocol


class EventType(str, Enum):
    CREATED = "sandbox.created"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_FINISHED = "execution.finished"
    FILE_WRITTEN = "file.written"
    FILE_READ = "file.read"
    SNAPSHOT_CREATED = "snapshot.created"
    SNAPSHOT_RESTORED = "snapshot.restored"
    FORKED = "sandbox.forked"
    DESTROYED = "sandbox.destroyed"
    POLICY_DENIED = "policy.denied"


@dataclass(frozen=True, slots=True)
class SandboxEvent:
    """One immutable audit event."""

    type: EventType
    sandbox_id: str
    timestamp: float = field(default_factory=time.time)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.type.value
        return payload


class EventObserver(Protocol):
    """Consumer for sandbox audit events."""

    def emit(self, event: SandboxEvent) -> None: ...


class MemoryObserver:
    """Thread-safe observer useful for tests and embedded audit trails."""

    def __init__(self) -> None:
        self._events: list[SandboxEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: SandboxEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[SandboxEvent, ...]:
        with self._lock:
            return tuple(self._events)


class JsonLogObserver:
    """Write audit events as structured JSON through Python logging."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("agentnest.audit")

    def emit(self, event: SandboxEvent) -> None:
        self._logger.info(json.dumps(event.to_dict(), sort_keys=True, default=str))


class OpenTelemetryObserver:
    """Emit one short OpenTelemetry span for every AgentNest audit event."""

    def __init__(self, tracer: Any | None = None) -> None:
        if tracer is None:
            trace = import_module("opentelemetry.trace")
            tracer = trace.get_tracer("agentnest")
        self._tracer = tracer

    def emit(self, event: SandboxEvent) -> None:
        with self._tracer.start_as_current_span(event.type.value) as span:
            span.set_attribute("agentnest.event_id", event.event_id)
            span.set_attribute("agentnest.sandbox_id", event.sandbox_id)
            for key, value in event.attributes.items():
                if isinstance(value, (str, bool, int, float)):
                    span.set_attribute(f"agentnest.{key}", value)
