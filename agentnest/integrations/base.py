"""Framework-neutral sandbox-backed Python runner."""

from __future__ import annotations

from agentnest.policy import SecurityPolicy
from agentnest.sandbox import Sandbox


class SandboxRunner:
    """Run agent-authored Python inside a hardened sandbox.

    By default the runner keeps a persistent session, so variables and imports
    an agent creates survive between calls -- the behaviour agents expect from a
    code tool. Set ``stateful=False`` for isolated one-shot executions instead.
    """

    def __init__(
        self,
        runtime: str = "python:3.12-slim",
        *,
        timeout: float = 300,
        network_enabled: bool = False,
        security_policy: SecurityPolicy | None = None,
        stateful: bool = True,
    ) -> None:
        self._sandbox = Sandbox(
            runtime,
            timeout,
            network_enabled=network_enabled,
            security_policy=security_policy,
        )
        self._session = self._sandbox.python_session() if stateful else None

    @property
    def sandbox(self) -> Sandbox:
        return self._sandbox

    def run(self, code: str) -> str:
        """Execute ``code`` and return a single combined text result."""

        if self._session is not None:
            outcome = self._session.run(code)
            parts = [outcome.stdout.strip()]
            if outcome.result is not None:
                parts.append(outcome.result)
            if outcome.error is not None:
                parts.append(outcome.error.strip())
            return "\n".join(part for part in parts if part).strip()
        result = self._sandbox.exec_python(code)
        return (result.stdout + result.stderr).strip()

    def close(self) -> None:
        self._sandbox.destroy()

    def __enter__(self) -> SandboxRunner:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
