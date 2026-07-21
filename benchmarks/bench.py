"""Measure AgentNest sandbox latencies on the local Docker backend.

Usage::

    python benchmarks/bench.py --iterations 20

Reports cold-start (create + destroy), warm exec round-trip, stateful-session
round-trip, and pooled-acquire latency. Numbers depend on the host and image
cache; publish the machine alongside them.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable

from agentnest import Sandbox, SandboxPool

IMAGE = "python:3.12-slim"


def _summary(name: str, samples: list[float]) -> str:
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return f"{name:<28} p50={p50 * 1000:8.1f} ms   p95={p95 * 1000:8.1f} ms   n={len(samples)}"


def _time(action: Callable[[], None]) -> float:
    start = time.perf_counter()
    action()
    return time.perf_counter() - start


def bench_cold_start(iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        sandbox = Sandbox(IMAGE, timeout=60)
        sandbox.destroy()
        samples.append(time.perf_counter() - start)
    return samples


def bench_warm_exec(iterations: int) -> list[float]:
    with Sandbox(IMAGE, timeout=120) as sandbox:
        sandbox.exec_shell("true")  # warm the exec path
        return [_time(lambda: sandbox.exec_shell("echo hi")) for _ in range(iterations)]


def bench_session(iterations: int) -> list[float]:
    with Sandbox(IMAGE, timeout=120) as sandbox:
        session = sandbox.python_session()
        session.run("x = 0")
        return [_time(lambda: session.run("x += 1")) for _ in range(iterations)]


def bench_pool_acquire(iterations: int) -> list[float]:
    pool = SandboxPool(lambda: Sandbox(IMAGE, timeout=120), size=2, max_uses=1000)
    try:

        def acquire() -> None:
            with pool.acquire() as sandbox:
                sandbox.exec_shell("true")

        return [_time(acquire) for _ in range(iterations)]
    finally:
        pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    arguments = parser.parse_args()
    n = arguments.iterations

    print(f"AgentNest benchmark  image={IMAGE}  iterations={n}\n")
    print(_summary("cold start (create+destroy)", bench_cold_start(max(5, n // 2))))
    print(_summary("warm exec round-trip", bench_warm_exec(n)))
    print(_summary("stateful session call", bench_session(n)))
    print(_summary("pooled acquire+exec", bench_pool_acquire(n)))


if __name__ == "__main__":
    main()
