from __future__ import annotations

import threading

import pytest

from agentnest import ExecutionTimeoutError
from agentnest.execution import run_with_timeout


def test_run_with_timeout_returns_value() -> None:
    assert run_with_timeout(lambda: 42, 1, lambda: None) == 42


def test_run_with_timeout_calls_cleanup() -> None:
    release = threading.Event()
    cleaned = threading.Event()

    with pytest.raises(ExecutionTimeoutError, match="sandbox was destroyed"):
        run_with_timeout(lambda: release.wait(1), 0.01, cleaned.set)

    release.set()
    assert cleaned.is_set()
