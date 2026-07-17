"""Compose policy, secret redaction, approvals, and structured events."""

from agentnest import (
    JsonLogObserver,
    NetworkPolicy,
    Sandbox,
    Secret,
    SecurityPolicy,
)

policy = SecurityPolicy(
    network=NetworkPolicy.denied(),
    max_output_bytes=2_000_000,
    allowed_images=("python:3.12-slim",),
)

with Sandbox(
    "python:3.12-slim",
    security_policy=policy,
    environment={"TOKEN": Secret("never-log-me")},
    observers=(JsonLogObserver(),),
) as sandbox:
    sandbox.write_file("main.py", "print('policy active')")
    sandbox.exec_shell("python main.py").check()
