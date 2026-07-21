# Benchmarks

These are latencies for the local Docker backend, produced by
[`benchmarks/bench.py`](https://github.com/mihirahuja1/agentnestOSS/blob/main/benchmarks/bench.py).
Reproduce them yourself:

```bash
python benchmarks/bench.py --iterations 20
```

## Results

Measured on a developer laptop running Docker Desktop (macOS, Docker 27.x), image
`python:3.12-slim` already pulled. Your numbers will differ; native Linux Docker
typically has faster cold starts than Docker Desktop's VM.

| Operation | p50 | p95 |
| --- | --- | --- |
| Cold start (create + destroy) | ~185 ms | ~1.9 s¹ |
| Warm exec round-trip | ~25 ms | ~60 ms |
| Stateful session call | ~24 ms | ~65 ms |
| Pooled acquire + exec | ~33 ms | ~45 ms |

¹ Cold-start p95 is dominated by the first few container starts while the daemon
warms up; steady-state cold starts sit near the p50.

## Reading these numbers

- **Cold start** is the full lifecycle of a fresh sandbox. For agents that make
  many short calls, avoid paying it repeatedly by holding a sandbox open across a
  task or borrowing from a [`SandboxPool`](guides/pools-artifacts.md).
- **Warm exec** is the steady-state cost of one command in an existing sandbox --
  the number that matters inside a tool-use loop.
- **Stateful session** shows that keeping a persistent interpreter alive costs no
  more per call than a fresh exec, while preserving variables and imports between
  calls.
- **Pooled acquire** amortizes cold start away: a warm pool hands back a ready
  sandbox in roughly the cost of one exec.

The methodology is deliberately simple (wall-clock around the public API) so the
script is easy to audit and adapt.
