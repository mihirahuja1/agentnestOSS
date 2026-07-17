from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import DockerException, ImageNotFound

from agentnest import RuntimeNotAvailableError, SandboxDestroyedError
from agentnest.models import ResourceLimits, SandboxConfig
from agentnest.runtime.docker import DockerRuntime


def docker_client() -> tuple[Mock, Mock]:
    client = Mock()
    container = Mock()
    client.containers.create.return_value = container
    return client, container


def test_create_applies_security_controls_and_destroy_cleans_workspace() -> None:
    client, container = docker_client()
    runtime = DockerRuntime(client=client)
    config = SandboxConfig(
        "python:test",
        30,
        {"APP_MODE": "test"},
        network_enabled=False,
        limits=ResourceLimits(memory="256m", cpus=0.5, pids=64),
    )

    runtime.create(config)
    workspace = runtime._workspace
    assert workspace is not None and workspace.exists()
    container.start.assert_called_once_with()
    settings = client.containers.create.call_args.kwargs
    assert settings["user"] == "65532:65532"
    assert settings["network_disabled"] is True
    assert settings["read_only"] is True
    assert settings["privileged"] is False
    assert settings["cap_drop"] == ["ALL"]
    assert settings["security_opt"] == ["no-new-privileges:true"]
    assert settings["mem_limit"] == "256m"
    assert settings["nano_cpus"] == 500_000_000
    assert settings["pids_limit"] == 64
    assert settings["environment"]["APP_MODE"] == "test"
    assert settings["volumes"] == {str(workspace): {"bind": "/workspace", "mode": "rw"}}

    runtime.destroy()
    container.remove.assert_called_once_with(force=True, v=True)
    assert not workspace.exists()
    runtime.destroy()


def test_create_pulls_missing_image() -> None:
    client, _ = docker_client()
    client.images.get.side_effect = ImageNotFound("missing")
    runtime = DockerRuntime(client=client)
    runtime.create(SandboxConfig("python:missing", 30))
    client.images.pull.assert_called_once_with("python:missing")
    runtime.destroy()


def test_create_failure_is_mapped_and_workspace_is_cleaned() -> None:
    client, _ = docker_client()
    client.ping.side_effect = DockerException("daemon unavailable")
    runtime = DockerRuntime(client=client)
    with pytest.raises(RuntimeNotAvailableError, match="daemon unavailable"):
        runtime.create(SandboxConfig("python:test", 30))
    assert runtime._workspace is None


def test_exec_files_and_logs() -> None:
    client, container = docker_client()
    container.exec_run.return_value = SimpleNamespace(exit_code=3, output=(b"out\n", b"err\n"))
    container.logs.return_value = b"container\n"
    runtime = DockerRuntime(client=client)
    runtime.create(SandboxConfig("python:test", 30))

    runtime.write_file("nested/input.txt", b"hello")
    assert runtime.read_file("nested/input.txt") == b"hello"
    result = runtime.exec(
        ["sh", "-c", "work"],
        display_command="work",
        environment={"KEY": "value"},
        workdir="/workspace/nested",
        timeout=2,
    )

    assert result.exit_code == 3
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert "$ work\n" in runtime.logs()
    assert "container\n" in runtime.logs()
    call = container.exec_run.call_args
    assert call.args[0] == ["sh", "-c", "work"]
    assert call.kwargs["environment"] == {"KEY": "value"}
    assert call.kwargs["user"] == "65532:65532"
    runtime.destroy()


def test_operations_require_live_sandbox() -> None:
    runtime = DockerRuntime(client=Mock())
    with pytest.raises(SandboxDestroyedError):
        runtime.read_file("missing")
    with pytest.raises(SandboxDestroyedError):
        runtime.exec(["true"], display_command="true")


def test_nested_workdir_is_created_for_non_root_user() -> None:
    client, _ = docker_client()
    runtime = DockerRuntime(client=client)
    runtime.create(SandboxConfig("python:test", 30, workdir="/workspace/project/src"))
    workspace = runtime._workspace
    assert workspace is not None
    assert (Path(workspace) / "project/src").is_dir()
    assert (Path(workspace) / "project/src").stat().st_mode & 0o777 == 0o777
    runtime.destroy()
