from __future__ import annotations

import os

import pytest

from agentnest import Sandbox

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENTNEST_DOCKER_TESTS") != "1",
        reason="set AGENTNEST_DOCKER_TESTS=1 to run Docker integration tests",
    ),
]


def test_python_files_shell_and_security_defaults() -> None:
    with Sandbox("python:3.12-slim", timeout=60) as sandbox:
        sandbox.write_file("input.txt", "nest")
        python_result = sandbox.exec_python(
            "from pathlib import Path; print(Path('input.txt').read_text().upper())"
        )
        shell_result = sandbox.exec_shell("id -u; touch output.txt; cat input.txt")
        output = sandbox.read_file("output.txt")

    assert python_result.stdout == "NEST\n"
    assert shell_result.stdout.startswith("65532\n")
    assert shell_result.stdout.endswith("nest")
    assert output == ""


def test_network_is_disabled_by_default() -> None:
    with Sandbox("python:3.12-slim", timeout=60) as sandbox:
        result = sandbox.exec_python(
            "import socket; socket.create_connection(('example.com', 80), timeout=1)"
        )
    assert not result.ok
