# Async and streaming

## Async lifecycle

```python
import asyncio
from agentnest import AsyncSandbox

async def main():
    sandbox = await AsyncSandbox.create(timeout=60)
    async with sandbox:
        result = await sandbox.exec_python("print('async')")
        print(result.stdout)

asyncio.run(main())
```

Construction uses a worker thread so image pulls and daemon calls do not block the event loop.

## Incremental output

```python
async with await AsyncSandbox.create() as sandbox:
    async for event in sandbox.stream_shell("pytest -v"):
        if event.stream in {"stdout", "stderr"}:
            print(event.data, end="")
        else:
            assert event.exit_code is not None
```

The final event has `stream="status"`. Streaming honors the deadline and aggregate output policy.
If the process is silent beyond its deadline, AgentNest still destroys the sandbox.
