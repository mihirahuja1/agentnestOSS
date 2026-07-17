# MCP, browser, GPU, and Git

## MCP tools

```bash
pip install 'agentnest[mcp]'
agentnest mcp
```

The server exposes create, execute Python, execute shell, read, write, and destroy tools. Run it in a
trusted environment and configure your MCP client to require approval for sensitive tools.

## Browser sandbox

```python
from agentnest.presets import browser_sandbox

with browser_sandbox(timeout=120) as sandbox:
    sandbox.exec_python("from playwright.sync_api import sync_playwright; print('ready')")
```

The preset selects a Playwright image and larger memory/PID defaults. Networking remains denied.
Pin the image by digest in production.

## GPU sandbox

```python
from agentnest.presets import gpu_sandbox

with gpu_sandbox("pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime", gpus=1) as sandbox:
    sandbox.exec_python("import torch; print(torch.cuda.is_available())")
```

Docker must have the NVIDIA Container Toolkit configured. GPU access is explicit and zero by default.

## Git workspace

```python
from agentnest import Sandbox
from agentnest.git import GitWorkspace

with Sandbox(network_enabled=True) as sandbox:
    repo = GitWorkspace(sandbox)
    repo.clone("https://github.com/example/project.git")
    sandbox.exec_shell("pytest", workdir=repo.directory)
    patch = repo.diff()
```

Credentials are never inherited from the host. Inject narrowly scoped credentials explicitly and
wrap them in `Secret`.
