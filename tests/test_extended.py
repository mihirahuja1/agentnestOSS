from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentnest import AsyncSandbox, JsonLogObserver, OpenTelemetryObserver, Sandbox
from agentnest.cli import main
from agentnest.events import EventType, SandboxEvent
from agentnest.git import GitWorkspace
from agentnest.models import ExecutionChunk, ResourceLimits, SandboxConfig
from agentnest.policy import NetworkPolicy, SecurityPolicy
from agentnest.presets import browser_sandbox, gpu_sandbox
from agentnest.profiles import SandboxProfile
from agentnest.runtime.kubernetes import KubernetesRuntime
from agentnest.runtime.remote import RemoteRuntime
from tests.fakes import FakeRuntime


class StreamingFake(FakeRuntime):
    def stream_exec(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        yield ExecutionChunk("stdout", "hello")
        yield ExecutionChunk("status", exit_code=0)


def test_async_streaming_bridge() -> None:
    async def scenario() -> None:
        sandbox = await AsyncSandbox.create(backend=StreamingFake())
        chunks = [chunk async for chunk in sandbox.stream_shell("work")]
        assert [chunk.stream for chunk in chunks] == ["stdout", "status"]
        await sandbox.destroy()

    asyncio.run(scenario())


def test_observers_emit_json_and_telemetry(caplog: pytest.LogCaptureFixture) -> None:
    event = SandboxEvent(EventType.CREATED, "sandbox", attributes={"image": "python"})
    with caplog.at_level(logging.INFO, logger="agentnest.audit"):
        JsonLogObserver().emit(event)
    assert '"type": "sandbox.created"' in caplog.text

    span = Mock()
    context = Mock()
    context.__enter__ = Mock(return_value=span)
    context.__exit__ = Mock(return_value=False)
    tracer = Mock()
    tracer.start_as_current_span.return_value = context
    OpenTelemetryObserver(tracer).emit(event)
    span.set_attribute.assert_any_call("agentnest.image", "python")


def test_yaml_profile_loads_policy(tmp_path: Path) -> None:
    profile_file = tmp_path / "agentnest.yaml"
    profile_file.write_text(
        "default:\n"
        "  runtime: python:test\n"
        "  network:\n"
        "    mode: allowlist\n"
        "    cidrs: [198.51.100.0/24]\n",
        encoding="utf-8",
    )
    profile = SandboxProfile.load(profile_file)
    assert profile.options["runtime"] == "python:test"
    policy = profile.options["security_policy"]
    assert isinstance(policy, SecurityPolicy)
    assert policy.network.cidrs == ("198.51.100.0/24",)


def test_git_workspace_commands_are_quoted() -> None:
    backend = FakeRuntime()
    sandbox = Sandbox(backend=backend)
    workspace = GitWorkspace(sandbox)
    workspace.clone("https://example.com/repo with space.git", ref="main")
    workspace.status()
    assert "'https://example.com/repo with space.git'" in backend.commands[0][1]
    assert backend.commands[1][3] == "/workspace/repo"
    sandbox.destroy()


def test_presets_apply_resource_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    constructor = Mock(return_value="sandbox")
    monkeypatch.setattr("agentnest.presets.Sandbox", constructor)
    assert browser_sandbox() == "sandbox"
    assert constructor.call_args.kwargs["memory"] == "2g"
    assert gpu_sandbox("cuda:test", gpus=2) == "sandbox"
    assert constructor.call_args.kwargs["gpus"] == 2


def test_cli_lists_backends_and_refuses_public_unauthenticated_api(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["backends"]) == 0
    assert "docker" in capsys.readouterr().out
    monkeypatch.delenv("AGENTNEST_API_TOKEN", raising=False)
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "Refusing" in capsys.readouterr().err


def test_kubernetes_manifest_has_hardening_and_gpu() -> None:
    runtime = KubernetesRuntime(runtime_class_name="gvisor")
    runtime._pod_name = "agentnest-test"
    config = SandboxConfig(
        "python:test",
        30,
        limits=ResourceLimits(memory="1Gi", cpus=1.0, pids=64, gpus=1),
    )
    manifest = runtime._pod_manifest(config)
    spec = manifest["spec"]
    container = spec["containers"][0]
    assert spec["automountServiceAccountToken"] is False
    assert spec["runtimeClassName"] == "gvisor"
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"

    runtime._networking = Mock()
    restricted = SandboxConfig(
        "python:test",
        30,
        security_policy=SecurityPolicy(network=NetworkPolicy.allowlist(cidrs=("198.51.100.0/24",))),
    )
    runtime._create_network_policy(restricted)
    policy = runtime._networking.create_namespaced_network_policy.call_args.args[1]
    assert policy["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] == "198.51.100.0/24"


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_remote_runtime_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[object] = []

    def urlopen(request: object, timeout: float) -> FakeResponse:
        requests.append(request)
        url = request.full_url  # type: ignore[attr-defined]
        if url.endswith("/v1/sandboxes"):
            return FakeResponse({"id": "remote-id"})
        if url.endswith("/exec"):
            return FakeResponse(
                {"command": "echo", "exit_code": 0, "stdout": "ok", "stderr": "", "duration": 0.1}
            )
        if url.endswith("/files/read"):
            return FakeResponse({"content": base64.b64encode(b"data").decode()})
        if url.endswith("/logs"):
            return FakeResponse({"logs": "remote logs"})
        return FakeResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    runtime = RemoteRuntime("https://runner.example", token="token")
    runtime.create(SandboxConfig("python:test", 30))
    assert runtime.exec(["echo"], display_command="echo").stdout == "ok"
    runtime.write_file("file", b"data")
    assert runtime.read_file("file") == b"data"
    assert runtime.logs() == "remote logs"
    runtime.destroy()
    assert len(requests) == 6
