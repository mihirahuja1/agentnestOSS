from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agentnest import (
    AsyncSandbox,
    MemoryObserver,
    NetworkPolicy,
    PolicyDeniedError,
    Sandbox,
    SandboxPool,
    Secret,
    SecurityPolicy,
    Template,
)
from agentnest.approvals import DenyAll
from agentnest.models import ExecutionResult
from agentnest.policy import NetworkMode
from agentnest.registry import RuntimeRegistry
from tests.fakes import FakeRuntime


class EchoRuntime(FakeRuntime):
    def exec(self, command: list[str], **kwargs: object) -> ExecutionResult:  # type: ignore[override]
        display = str(kwargs["display_command"])
        environment = kwargs.get("environment") or {}
        assert isinstance(environment, dict)
        output = environment.get("TOKEN", "{}")
        self._last_output = str(output)
        return ExecutionResult(display, 0, str(output), "", 0.01)

    def logs(self) -> str:
        return getattr(self, "_last_output", "")


def test_secret_redaction_events_and_exec_json() -> None:
    observer = MemoryObserver()
    backend = EchoRuntime()
    sandbox = Sandbox(
        backend=backend,
        environment={"TOKEN": Secret("top-secret")},
        observers=(observer,),
    )
    result = sandbox.exec_shell("print token", environment={"TOKEN": Secret("command-secret")})
    assert result.stdout == "[REDACTED]"
    assert sandbox.logs() == "[REDACTED]"

    parsed = sandbox.exec_json("print json", environment={"TOKEN": json.dumps({"ok": True})})
    assert parsed == {"ok": True}
    sandbox.destroy()
    assert [event.type.value for event in observer.events] == [
        "sandbox.created",
        "execution.started",
        "execution.finished",
        "execution.started",
        "execution.finished",
        "sandbox.destroyed",
    ]


def test_approval_hook_denies_before_execution() -> None:
    backend = FakeRuntime()
    sandbox = Sandbox(backend=backend, approval_hook=DenyAll())
    with pytest.raises(PolicyDeniedError, match="execute_shell"):
        sandbox.exec_shell("danger")
    assert backend.commands == []
    sandbox.destroy()


def test_network_and_image_policy_validation() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        NetworkPolicy(NetworkMode.ALLOWLIST)
    with pytest.raises(ValueError, match="only valid"):
        NetworkPolicy(NetworkMode.DENY, domains=("example.com",))
    with pytest.raises(ValueError, match="sha256"):
        SecurityPolicy(require_image_digest=True).validate_image("python:3.12")
    SecurityPolicy(allowed_images=("python:3.12",)).validate_image("python:3.12")


def test_template_is_immutable_and_reproducible() -> None:
    template = (
        Template("python:3.12-slim")
        .apt_install("git")
        .pip_install("requests==2.32.3")
        .with_environment(MODE="test value")
        .run("python -V")
    )
    dockerfile = template.dockerfile()
    assert dockerfile.startswith("FROM python:3.12-slim\n")
    assert "apt-get install" in dockerfile
    assert "requests==2.32.3" in dockerfile
    assert 'ENV MODE="test value"' in dockerfile
    assert dockerfile.endswith("RUN python -V\n")


def test_runtime_registry_supports_custom_backends() -> None:
    registry = RuntimeRegistry()
    backend = FakeRuntime()
    registry.register("test", lambda: backend)
    assert registry.create("TEST") is backend
    assert registry.names() == ("test",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("test", FakeRuntime)


def test_pool_reuses_then_replaces_sandboxes() -> None:
    created: list[Sandbox] = []

    def factory() -> Sandbox:
        sandbox = Sandbox(backend=FakeRuntime())
        created.append(sandbox)
        return sandbox

    with SandboxPool(factory, size=1, max_uses=2) as pool:
        with pool.acquire(timeout=0.1) as first:
            first_id = first.id
        with pool.acquire(timeout=0.1) as second:
            assert second.id == first_id
        with pool.acquire(timeout=0.1) as third:
            assert third.id != first_id
    assert all(sandbox.destroyed for sandbox in created)


def test_async_sandbox_wraps_sync_api() -> None:
    async def scenario() -> None:
        sandbox = await AsyncSandbox.create(backend=FakeRuntime())
        async with sandbox:
            result = await sandbox.exec_shell("echo async")
            assert result.stdout == "ok\n"
        assert sandbox.destroyed

    asyncio.run(scenario())


def test_upload_download_remains_binary_safe(tmp_path: Path) -> None:
    sandbox = Sandbox(backend=FakeRuntime())
    source = tmp_path / "source"
    source.write_bytes(b"\x00\xff")
    sandbox.upload_file(source, "source")
    destination = tmp_path / "destination"
    sandbox.download_file("source", destination)
    assert destination.read_bytes() == b"\x00\xff"
    sandbox.destroy()
