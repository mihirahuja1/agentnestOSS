"""Live fork tests. Require Docker.

Run with::

    AGENTNEST_DOCKER_TESTS=1 pytest -m integration tests/test_fork_integration.py
"""

from __future__ import annotations

import os

import pytest

from agentnest import Sandbox

pytestmark = pytest.mark.integration

if not os.environ.get("AGENTNEST_DOCKER_TESTS"):
    pytest.skip("set AGENTNEST_DOCKER_TESTS=1 to run Docker tests", allow_module_level=True)


def test_fork_copies_state_then_diverges() -> None:
    with Sandbox("python:3.12-slim", timeout=120) as parent:
        parent.write_file("data.txt", "shared")
        child = parent.fork()
        try:
            # The child starts from a copy of the parent's workspace.
            assert child.read_file("data.txt") == "shared"
            # Writes after the split are isolated in both directions.
            child.write_file("data.txt", "changed by child")
            parent.write_file("only_parent.txt", "p")
            assert child.read_file("data.txt") == "changed by child"
            assert parent.read_file("data.txt") == "shared"
            assert child.exec_shell("cat only_parent.txt").exit_code != 0
        finally:
            child.destroy()


def test_fork_preserves_installed_workspace_packages() -> None:
    with Sandbox("python:3.12-slim", timeout=180, network_enabled=True) as parent:
        parent.exec_shell("pip install --user --quiet cowsay==6.1").check()
        child = parent.fork()
        try:
            # A package installed into the workspace-local site is inherited.
            assert child.exec_python("import cowsay; print(cowsay.__name__)").ok
        finally:
            child.destroy()
