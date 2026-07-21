"""Give a LangChain agent a sandboxed Python tool.

Run:  pip install langchain-core  (and your model provider), then this file.
"""

from __future__ import annotations

from agentnest.integrations import SandboxRunner
from agentnest.integrations.langchain import build_langchain_tool


def main() -> None:
    # One sandbox, reused across tool calls, with state persisting between them.
    with SandboxRunner(network_enabled=False) as runner:
        tool = build_langchain_tool(runner)
        # Hand `tool` to any LangChain agent via `.bind_tools([tool])` or an
        # AgentExecutor. Here we just invoke it directly.
        print(tool.invoke({"code": "nums = [n * n for n in range(5)]; print(sum(nums))"}))


if __name__ == "__main__":
    main()
