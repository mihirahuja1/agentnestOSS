"""Helpers for bounded backend execution."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TypeVar

from agentnest.exceptions import ExecutionTimeoutError

T = TypeVar("T")


def run_with_timeout(
    operation: Callable[[], T], timeout: float, on_timeout: Callable[[], None]
) -> T:
    """Run a blocking backend call and tear down its sandbox on timeout."""

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agentnest-exec")
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        on_timeout()
        raise ExecutionTimeoutError(
            f"execution exceeded {timeout:g} seconds; the sandbox was destroyed"
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
