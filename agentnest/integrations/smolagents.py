"""smolagents-compatible Python executor backed by an AgentNest sandbox.

smolagents lets a ``CodeAgent`` delegate code execution to a custom executor.
This adapter runs that code in a hardened AgentNest sandbox instead of on the
host, so a smolagents agent gains isolation, egress control, and audit events
without any other change. Experimental: it tracks smolagents' executor duck type
(``__call__``, ``send_variables``, ``send_tools``).
"""

from __future__ import annotations

from typing import Any

from agentnest.integrations.base import SandboxRunner


class SandboxExecutor:
    """Execute smolagents code actions inside an AgentNest sandbox."""

    def __init__(self, **runner_kwargs: Any) -> None:
        self._runner = SandboxRunner(**runner_kwargs)

    def __call__(self, code_action: str) -> tuple[str, str, bool]:
        """Run one code action, returning ``(output, logs, is_final_answer)``."""

        output = self._runner.run(code_action)
        return output, output, False

    def send_variables(self, variables: dict[str, Any]) -> None:
        """Best-effort injection of simple repr-able variables into the session."""

        for name, value in variables.items():
            self._runner.run(f"{name} = {value!r}")

    def send_tools(self, tools: dict[str, Any]) -> None:
        """AgentNest does not import host tool callables into the sandbox."""

    def cleanup(self) -> None:
        self._runner.close()
