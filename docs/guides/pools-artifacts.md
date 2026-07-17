# Pools and artifacts

## Warm pools

```python
from agentnest import Sandbox, SandboxPool

with SandboxPool(lambda: Sandbox(timeout=900), size=4, max_uses=20) as pool:
    with pool.acquire(timeout=5) as sandbox:
        sandbox.exec_python("print('ready')")
```

Pools are bounded. A sandbox is replaced when destroyed or when it reaches its maximum reuse count.
Closing a pool destroys available instances; borrowed instances are destroyed when returned.

Applications must clear tenant data between reuse. For multi-tenant workloads, prefer a clean
snapshot restore or `max_uses=1` until a backend provides a proven reset primitive.

## Discover artifacts

```python
for artifact in sandbox.artifacts("dist/**/*"):
    print(artifact.path, artifact.size, artifact.sha256)
```

Artifacts include regular, non-symlink files and use paths relative to `/workspace`.
