"""Consume sandbox output without blocking an asyncio event loop."""

import asyncio

from agentnest import AsyncSandbox


async def main() -> None:
    sandbox = await AsyncSandbox.create(timeout=60)
    async with sandbox:
        async for event in sandbox.stream_shell("for n in 1 2 3; do echo stream:$n; sleep 1; done"):
            if event.stream == "status":
                print(f"exit={event.exit_code}")
            else:
                print(event.data, end="")


if __name__ == "__main__":
    asyncio.run(main())
