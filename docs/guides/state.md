# Templates and snapshots

## Build a reusable template

```python
from agentnest import Sandbox, Template

template = (
    Template("python:3.12-slim")
    .apt_install("git")
    .pip_install("requests==2.32.3", "pydantic==2.10.6")
    .with_environment(PYTHONDONTWRITEBYTECODE="1")
)
image = template.build()
```

Without an explicit tag, the image name includes a hash of the Dockerfile. Identical templates reuse
Docker's build cache and image.

## Snapshot workspace state

```python
with Sandbox() as sandbox:
    sandbox.exec_shell("python prepare_dataset.py").check()
    metadata = sandbox.snapshot("checkpoint.tar")

with Sandbox() as fork:
    fork.restore("checkpoint.tar")
```

Docker snapshots use the daemon's container-namespace archive API, keeping host paths outside the
sandbox invisible. Snapshots contain workspace filesystem state—not process memory.
