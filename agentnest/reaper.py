"""Reap managed Docker resources left behind by crashed processes.

A sandbox's lifetime timer lives in the owning process. If that process is
killed, its container, egress proxy, and internal network can linger. Every
resource AgentNest creates carries an ``agentnest.managed=true`` label and an
``agentnest.deadline`` epoch, so this module -- and ``agentnest prune`` -- can
find and remove anything past its lifetime without help from the original
process.
"""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.client import DockerClient

_MANAGED_FILTER: dict[str, str | list[str] | bool] = {"label": "agentnest.managed=true"}
# Extra slack past the deadline before reaping, so a sandbox that is mid-destroy
# in a healthy process is never yanked out from under it.
_DEFAULT_GRACE = 60.0


@dataclass(frozen=True, slots=True)
class PruneReport:
    """What a prune pass removed."""

    containers: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.containers) + len(self.networks)


def _expired(labels: dict[str, str], now: float, grace: float) -> bool:
    raw = labels.get("agentnest.deadline")
    if raw is None:
        return False
    try:
        return now >= float(raw) + grace
    except ValueError:
        return False


def prune(
    client: DockerClient | None = None,
    *,
    force_all: bool = False,
    grace: float = _DEFAULT_GRACE,
) -> PruneReport:
    """Remove managed sandbox resources that are past their deadline.

    With ``force_all`` every managed resource is removed regardless of deadline,
    which is useful for tearing down a development machine.
    """

    from docker.errors import DockerException

    if client is None:
        import docker

        client = docker.from_env()

    now = time.time()
    report = PruneReport()

    for container in client.containers.list(all=True, filters=_MANAGED_FILTER):
        if force_all or _expired(container.labels or {}, now, grace):
            with suppress(DockerException):
                container.remove(force=True, v=True)
                report.containers.append(str(container.name))

    for network in client.networks.list(filters=_MANAGED_FILTER):
        labels = network.attrs.get("Labels") or {}
        if force_all or _expired(labels, now, grace):
            with suppress(DockerException):
                network.reload()
                for connected in network.containers:
                    with suppress(DockerException):
                        network.disconnect(connected, force=True)
                network.remove()
                report.networks.append(str(network.name))

    return report
