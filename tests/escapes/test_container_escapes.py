"""Adversarial tests against the live Docker sandbox hardening.

Each test tries to break out of, or abuse, the container and asserts the control
holds. Run with::

    AGENTNEST_DOCKER_TESTS=1 pytest -m integration tests/escapes/test_container_escapes.py
"""

from __future__ import annotations

import os

import pytest

from agentnest import NetworkPolicy, Sandbox, SecurityPolicy

pytestmark = pytest.mark.integration

if not os.environ.get("AGENTNEST_DOCKER_TESTS"):
    pytest.skip("set AGENTNEST_DOCKER_TESTS=1 to run Docker tests", allow_module_level=True)


@pytest.fixture(scope="module")
def sandbox():  # type: ignore[no-untyped-def]
    box = Sandbox("python:3.12-slim", timeout=120)
    try:
        yield box
    finally:
        box.destroy()


def test_process_runs_as_non_root(sandbox: Sandbox) -> None:
    assert sandbox.exec_shell("id -u").stdout.strip() == "65532"


def test_all_capabilities_are_dropped(sandbox: Sandbox) -> None:
    effective = sandbox.exec_shell("grep CapEff /proc/self/status").stdout.strip()
    assert effective.endswith("0000000000000000")


def test_no_new_privileges_is_set(sandbox: Sandbox) -> None:
    status = sandbox.exec_shell("grep NoNewPrivs /proc/self/status").stdout
    assert status.split()[-1] == "1"


def test_root_filesystem_is_read_only(sandbox: Sandbox) -> None:
    assert (
        sandbox.exec_shell("touch /root/escape 2>&1 || echo BLOCKED")
        .stdout.strip()
        .endswith("BLOCKED")
    )
    assert (
        sandbox.exec_shell("touch /usr/bin/escape 2>&1 || echo BLOCKED")
        .stdout.strip()
        .endswith("BLOCKED")
    )


def test_tmp_is_mounted_noexec(sandbox: Sandbox) -> None:
    script = (
        "printf '#!/bin/sh\\necho pwned\\n' > /tmp/x && chmod +x /tmp/x && "
        "(/tmp/x 2>&1 || echo BLOCKED)"
    )
    assert "pwned" not in sandbox.exec_shell(script).stdout


def test_default_sandbox_has_no_network(sandbox: Sandbox) -> None:
    probe = sandbox.exec_python(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=5); print('REACHED')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    )
    assert probe.stdout.strip() == "BLOCKED"


def test_output_flood_is_bounded() -> None:
    policy = SecurityPolicy(network=NetworkPolicy.denied(), max_output_bytes=2000)
    with Sandbox("python:3.12-slim", timeout=60, security_policy=policy) as box:
        result = box.exec_python("print('x' * 500000)")
        assert len(result.stdout) <= 4000
        assert "truncated" in result.stderr


def test_pid_limit_contains_a_fork_bomb() -> None:
    policy = SecurityPolicy(network=NetworkPolicy.denied())
    with Sandbox("python:3.12-slim", timeout=60, pids=64, security_policy=policy) as box:
        # Spawning far past the PID cap must fail inside the container, not take
        # down the host, and the sandbox must remain usable afterwards.
        box.exec_shell("for i in $(seq 1 500); do sleep 30 & done 2>/dev/null; true", timeout=20)
        assert not box.destroyed
        assert box.exec_shell("echo alive").stdout.strip() == "alive"
