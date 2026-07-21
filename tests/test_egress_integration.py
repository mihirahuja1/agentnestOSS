"""Live egress-proxy tests. Require Docker and outbound network access.

Run with::

    AGENTNEST_DOCKER_TESTS=1 pytest -m integration tests/test_egress_integration.py
"""

from __future__ import annotations

import os

import pytest

from agentnest import NetworkPolicy, Sandbox, SecurityPolicy

pytestmark = pytest.mark.integration

if not os.environ.get("AGENTNEST_DOCKER_TESTS"):
    pytest.skip("set AGENTNEST_DOCKER_TESTS=1 to run Docker tests", allow_module_level=True)


_PROBE = """
import urllib.request
try:
    urllib.request.urlopen({url!r}, timeout=15).read(1)
    print("REACHED")
except Exception as exc:  # noqa: BLE001
    print("BLOCKED", type(exc).__name__)
"""


def _run(policy: SecurityPolicy, url: str) -> str:
    with Sandbox("python:3.12-slim", timeout=90, security_policy=policy) as sandbox:
        return sandbox.exec_python(_PROBE.format(url=url)).stdout.strip()


def test_allowlisted_domain_is_reachable() -> None:
    policy = SecurityPolicy(network=NetworkPolicy.allowlist(domains=("pypi.org",)))
    assert _run(policy, "https://pypi.org/simple/").startswith("REACHED")


def test_unlisted_domain_is_blocked() -> None:
    policy = SecurityPolicy(network=NetworkPolicy.allowlist(domains=("pypi.org",)))
    assert _run(policy, "https://example.com").startswith("BLOCKED")


def test_denied_policy_has_no_network() -> None:
    policy = SecurityPolicy(network=NetworkPolicy.denied())
    assert _run(policy, "https://pypi.org/simple/").startswith("BLOCKED")
