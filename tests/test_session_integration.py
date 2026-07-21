"""Live tests for stateful sessions and non-destructive timeouts.

Run with::

    AGENTNEST_DOCKER_TESTS=1 pytest -m integration tests/test_session_integration.py
"""

from __future__ import annotations

import os

import pytest

from agentnest import ExecutionTimeoutError, Sandbox

pytestmark = pytest.mark.integration

if not os.environ.get("AGENTNEST_DOCKER_TESTS"):
    pytest.skip("set AGENTNEST_DOCKER_TESTS=1 to run Docker tests", allow_module_level=True)


def test_session_persists_state_across_calls() -> None:
    with Sandbox("python:3.12-slim", timeout=90) as sandbox:
        session = sandbox.python_session()
        session.run("x = 40").check()
        session.run("import math").check()
        result = session.run("x + 2").check()
        assert result.result == "42"
        printed = session.run("print('hi', math.floor(3.9))").check()
        assert printed.stdout.strip() == "hi 3"


def test_session_reports_errors_without_dying() -> None:
    with Sandbox("python:3.12-slim", timeout=90) as sandbox:
        session = sandbox.python_session()
        failed = session.run("1 / 0")
        assert not failed.ok
        assert "ZeroDivisionError" in (failed.error or "")
        # The interpreter survives the exception and keeps its namespace.
        session.run("recovered = 7").check()
        assert session.run("recovered").check().result == "7"


def test_command_timeout_keeps_sandbox_alive() -> None:
    with Sandbox("python:3.12-slim", timeout=120) as sandbox:
        sandbox.write_file("keep.txt", "precious")
        with pytest.raises(ExecutionTimeoutError):
            sandbox.exec_shell("sleep 30", timeout=2)
        # The slow command was killed but the sandbox and its files remain.
        assert not sandbox.destroyed
        assert sandbox.read_file("keep.txt") == "precious"
        assert sandbox.exec_python("print('still here')").stdout.strip() == "still here"
