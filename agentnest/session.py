"""Stateful Python sessions backed by a persistent in-sandbox interpreter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentnest.exceptions import ExecutionError, ExecutionTimeoutError, FileAccessError

if TYPE_CHECKING:
    from agentnest.sandbox import Sandbox

_SERVER_SOURCE = Path(__file__).with_name("_repl_server.py")
_SESSION_DIR = ".agentnest-repl"
_POLL_INTERVAL = 0.02


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Outcome of one :class:`PythonSession` evaluation."""

    stdout: str
    stderr: str
    result: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the snippet ran without raising."""

        return self.error is None

    def check(self) -> SessionResult:
        """Return this result or raise when the snippet raised."""

        if self.error is not None:
            raise ExecutionError(self.error.strip().splitlines()[-1])
        return self


class PythonSession:
    """A long-lived interpreter whose namespace persists across calls.

    Unlike :meth:`Sandbox.exec_python`, which runs a fresh process each time,
    variables and imports created here survive between :meth:`run` calls -- the
    workflow a data or coding agent needs when it builds up state step by step.
    """

    def __init__(self, sandbox: Sandbox, *, start_timeout: float = 30.0) -> None:
        self._sandbox = sandbox
        self._start_timeout = start_timeout
        self._index = 0
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        source = _SERVER_SOURCE.read_text(encoding="utf-8")
        self._sandbox.write_file(f"{_SESSION_DIR}/server.py", source)
        # Background the interpreter; it is reparented to the container init and
        # runs until the sandbox is destroyed.
        self._sandbox.exec_shell(
            f"nohup python /workspace/{_SESSION_DIR}/server.py "
            f">/workspace/{_SESSION_DIR}/server.log 2>&1 &",
            timeout=15,
        )
        self._started = True

    def run(self, code: str, *, timeout: float = 30.0) -> SessionResult:
        """Evaluate ``code`` in the session and return its captured output."""

        if not self._started:
            self.start()
        index = self._index
        self._sandbox.write_file(f"{_SESSION_DIR}/req-{index}.py", code)
        response_path = f"{_SESSION_DIR}/resp-{index}.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload = self._sandbox.read_file(response_path)
            except FileAccessError:
                time.sleep(_POLL_INTERVAL)
                continue
            assert isinstance(payload, str)
            self._index += 1
            data = json.loads(payload)
            return SessionResult(
                stdout=data["stdout"],
                stderr=data["stderr"],
                result=data.get("result"),
                error=data.get("error"),
            )
        raise ExecutionTimeoutError(f"python session call exceeded {timeout:g} seconds")
