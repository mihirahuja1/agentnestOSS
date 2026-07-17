# Quickstart

Create a secure local sandbox in a few minutes.

## 1. Install

You need Python 3.10+ and a running Docker daemon.

```bash
python -m venv .venv
source .venv/bin/activate
pip install agentnest
agentnest doctor
```

For a checkout of this repository, use `pip install -e '.[dev]'`.

## 2. Execute code

```python
from agentnest import Sandbox

with Sandbox("python:3.12-slim", timeout=60) as sandbox:
    result = sandbox.exec_python("print(sum(range(10)))")
    result.check()
    print(result.stdout)  # 45
```

`ExecutionResult` contains `exit_code`, `stdout`, `stderr`, `duration`, and `ok`. A non-zero process
exit is data, not an infrastructure exception; call `.check()` when you want failure to raise.

## 3. Exchange files

```python
with Sandbox() as sandbox:
    sandbox.write_file("input.txt", "agentnest")
    sandbox.exec_shell("tr a-z A-Z < input.txt > output.txt").check()
    print(sandbox.read_file("output.txt"))
```

All sandbox paths are relative to `/workspace`. Absolute paths, traversal, and symlink escape races
are rejected.

## 4. Install packages

Networking is denied unless you explicitly enable it:

```python
from agentnest import NetworkPolicy, SecurityPolicy

policy = SecurityPolicy(network=NetworkPolicy.allowed())
with Sandbox(security_policy=policy) as sandbox:
    sandbox.exec_shell("pip install requests").check()
```

Use a template when dependencies are reused across many sandboxes.

## 5. Stream output

```python
with Sandbox() as sandbox:
    for event in sandbox.stream_shell("for n in 1 2 3; do echo $n; sleep 1; done"):
        if event.stream in {"stdout", "stderr"}:
            print(event.data, end="")
        else:
            print("exit:", event.exit_code)
```

## 6. Clean up

Prefer a context manager. `destroy()` is idempotent, and AgentNest also enforces the total lifetime
timer. A command timeout destroys the whole environment before raising so code cannot continue in
the background.

Next: configure [policies and secrets](guides/policies.md), or learn how the [runtime architecture](architecture.md) works.
