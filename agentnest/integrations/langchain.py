"""LangChain tool adapter for AgentNest."""

from __future__ import annotations

from typing import Any

from agentnest.exceptions import AgentNestError
from agentnest.integrations.base import SandboxRunner

_DESCRIPTION = (
    "Execute Python code in a secure, isolated sandbox and return its output. "
    "State persists across calls within a session. Use for any code the agent "
    "should not run on the host."
)


def build_langchain_tool(
    runner: SandboxRunner | None = None,
    *,
    name: str = "python_sandbox",
    description: str = _DESCRIPTION,
    **runner_kwargs: Any,
) -> Any:
    """Build a LangChain ``StructuredTool`` backed by an AgentNest sandbox.

    Install LangChain separately (``pip install langchain-core``). Pass a shared
    :class:`SandboxRunner` to reuse one sandbox, or keyword arguments to create
    one (for example ``network_enabled=True``).
    """

    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise AgentNestError(
            "the LangChain integration requires: pip install langchain-core"
        ) from exc

    active = runner or SandboxRunner(**runner_kwargs)

    def run_python(code: str) -> str:
        return active.run(code)

    return StructuredTool.from_function(func=run_python, name=name, description=description)
