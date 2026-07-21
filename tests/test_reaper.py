from __future__ import annotations

import time
from unittest.mock import Mock

from agentnest.reaper import PruneReport, _expired, prune


def test_expired_respects_deadline_and_grace() -> None:
    now = time.time()
    assert _expired({"agentnest.deadline": str(now - 100)}, now, grace=60)
    assert not _expired({"agentnest.deadline": str(now - 10)}, now, grace=60)
    assert not _expired({"agentnest.deadline": str(now + 100)}, now, grace=60)
    assert not _expired({}, now, grace=60)
    assert not _expired({"agentnest.deadline": "not-a-number"}, now, grace=60)


def test_prune_removes_only_expired_by_default() -> None:
    now = time.time()
    expired = Mock()
    expired.name = "expired"
    expired.labels = {"agentnest.deadline": str(now - 1000)}
    fresh = Mock()
    fresh.name = "fresh"
    fresh.labels = {"agentnest.deadline": str(now + 1000)}
    client = Mock()
    client.containers.list.return_value = [expired, fresh]
    client.networks.list.return_value = []

    report = prune(client)
    assert report.containers == ["expired"]
    expired.remove.assert_called_once_with(force=True, v=True)
    fresh.remove.assert_not_called()


def test_prune_force_all_removes_everything() -> None:
    now = time.time()
    fresh = Mock()
    fresh.name = "fresh"
    fresh.labels = {"agentnest.deadline": str(now + 1000)}
    client = Mock()
    client.containers.list.return_value = [fresh]
    client.networks.list.return_value = []

    report = prune(client, force_all=True)
    assert report.containers == ["fresh"]
    assert isinstance(report, PruneReport)
