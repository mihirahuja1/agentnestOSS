"""Docker implementation of the AgentNest runtime contract."""

from __future__ import annotations

import hashlib
import queue
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.types import DeviceRequest

from agentnest.exceptions import (
    ExecutionError,
    ExecutionTimeoutError,
    FileAccessError,
    RuntimeNotAvailableError,
    SandboxDestroyedError,
    UnsupportedCapabilityError,
)
from agentnest.execution import run_with_timeout
from agentnest.filesystem import atomic_write, bounded_read
from agentnest.models import ExecutionChunk, ExecutionResult, SandboxConfig, SnapshotMetadata
from agentnest.runtime.base import RuntimeBackend

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container


_SANDBOX_UID = 65532
_DEFAULT_PATH = "/workspace/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"


class DockerRuntime(RuntimeBackend):
    """Run one sandbox in a hardened Docker container."""

    def __init__(
        self, client: DockerClient | None = None, *, runtime_name: str | None = None
    ) -> None:
        self._client = client
        self._container: Container | None = None
        self._workspace: Path | None = None
        self._config: SandboxConfig | None = None
        self._execution_logs: list[str] = []
        self._lock = threading.RLock()
        self._runtime_name = runtime_name

    def create(self, config: SandboxConfig) -> None:
        with self._lock:
            if self._container is not None:
                raise RuntimeNotAvailableError("this Docker runtime already owns a sandbox")

            config.security_policy.validate_image(config.image)
            if config.security_policy.network.mode.value == "allowlist":
                raise UnsupportedCapabilityError(
                    "the Docker backend cannot enforce domain/CIDR allowlists; "
                    "use a policy-aware backend"
                )

            workspace = Path(tempfile.mkdtemp(prefix="agentnest-"))
            # The directory is an unguessable, dedicated mount. World write access lets
            # the fixed non-root container UID use it on Linux without root-side chown.
            workspace.chmod(0o777)
            self._workspace = workspace
            self._config = config

            relative_workdir = config.workdir.removeprefix("/workspace").lstrip("/")
            if relative_workdir:
                workdir_path = workspace / relative_workdir
                workdir_path.mkdir(parents=True, exist_ok=True)
                workdir_path.chmod(0o777)

            try:
                client = self._client or docker.from_env()
                client.ping()
                self._client = client
                if config.security_policy.rootless:
                    security_options = " ".join(client.info().get("SecurityOptions", ()))
                    if "rootless" not in security_options.lower():
                        raise UnsupportedCapabilityError(
                            "security policy requires a rootless Docker daemon"
                        )
                try:
                    client.images.get(config.image)
                except ImageNotFound:
                    client.images.pull(config.image)

                environment = {
                    "HOME": "/workspace/.agentnest-home",
                    "PATH": _DEFAULT_PATH,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONUSERBASE": "/workspace/.local",
                    **dict(config.environment),
                }
                security_opt = ["no-new-privileges:true"]
                if config.security_policy.seccomp_profile:
                    security_opt.append(f"seccomp={config.security_policy.seccomp_profile}")
                if config.security_policy.apparmor_profile:
                    security_opt.append(f"apparmor={config.security_policy.apparmor_profile}")
                device_requests = (
                    [DeviceRequest(count=config.limits.gpus, capabilities=[["gpu"]])]
                    if config.limits.gpus
                    else None
                )
                create_options: dict[str, Any] = {
                    "runtime": self._runtime_name,
                    "device_requests": device_requests,
                }
                self._container = client.containers.create(
                    image=config.image,
                    command=["sh", "-c", "while :; do sleep 3600; done"],
                    detach=True,
                    environment=environment,
                    working_dir=config.workdir,
                    user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
                    network_disabled=config.security_policy.network.mode.value == "deny",
                    read_only=config.read_only_root,
                    privileged=False,
                    cap_drop=["ALL"],
                    security_opt=security_opt,
                    mem_limit=config.limits.memory,
                    nano_cpus=int(config.limits.cpus * 1_000_000_000),
                    pids_limit=config.limits.pids,
                    init=True,
                    tmpfs={
                        "/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=1777",
                        "/run": "rw,noexec,nosuid,nodev,size=16m,mode=755",
                    },
                    volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                    labels={"agentnest.managed": "true"},
                    **{key: value for key, value in create_options.items() if value is not None},
                )
                self._container.start()
            except UnsupportedCapabilityError:
                self._cleanup_failed_create()
                raise
            except (DockerException, OSError) as exc:
                self._cleanup_failed_create()
                raise RuntimeNotAvailableError(f"could not create Docker sandbox: {exc}") from exc

    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        container = self._require_container()
        config = self._require_config()
        effective_timeout = timeout if timeout is not None else config.timeout
        started = time.monotonic()

        def operation() -> Any:
            try:
                return container.exec_run(
                    command,
                    demux=True,
                    environment=dict(environment or {}),
                    workdir=workdir or config.workdir,
                    user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
                )
            except (DockerException, OSError) as exc:
                raise ExecutionError(f"Docker execution failed: {exc}") from exc

        response = run_with_timeout(operation, effective_timeout, self.destroy)
        stdout_raw, stderr_raw = response.output
        stdout, stderr = self._bounded_outputs(stdout_raw or b"", stderr_raw or b"", config)
        result = ExecutionResult(
            command=display_command,
            exit_code=int(response.exit_code),
            stdout=stdout,
            stderr=stderr,
            duration=time.monotonic() - started,
        )
        with self._lock:
            self._execution_logs.append(self._format_log(result))
        return result

    def stream_exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[ExecutionChunk]:
        """Stream a Docker exec process while retaining hard timeout cleanup."""

        self._require_container()
        config = self._require_config()
        client = self._client
        if client is None:
            raise SandboxDestroyedError("the Docker client is unavailable")
        effective_timeout = timeout or config.timeout
        execution = client.api.exec_create(
            self._require_container().id,
            command,
            environment=dict(environment or {}),
            workdir=workdir or config.workdir,
            user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
        )
        execution_id = execution["Id"]
        messages: queue.Queue[tuple[bytes | None, bytes | None] | BaseException | None] = (
            queue.Queue()
        )

        def consume() -> None:
            try:
                for output in client.api.exec_start(execution_id, stream=True, demux=True):
                    messages.put(output)
            except BaseException as exc:
                messages.put(exc)
            finally:
                messages.put(None)

        worker = threading.Thread(target=consume, daemon=True, name="agentnest-stream")
        worker.start()
        deadline = time.monotonic() + effective_timeout
        log_parts = [f"$ {display_command}\n"]
        remaining_output = config.security_policy.max_output_bytes
        truncated = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.destroy()
                raise ExecutionTimeoutError(
                    f"execution exceeded {effective_timeout:g} seconds; the sandbox was destroyed"
                )
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty as exc:
                self.destroy()
                raise ExecutionTimeoutError(
                    f"execution exceeded {effective_timeout:g} seconds; the sandbox was destroyed"
                ) from exc
            if message is None:
                break
            if isinstance(message, BaseException):
                raise ExecutionError(f"Docker streaming execution failed: {message}") from message
            stdout, stderr = message
            if stdout:
                data, remaining_output, did_truncate = self._stream_data(stdout, remaining_output)
                truncated = truncated or did_truncate
                if data:
                    log_parts.append(data)
                    yield ExecutionChunk("stdout", data)
            if stderr:
                data, remaining_output, did_truncate = self._stream_data(stderr, remaining_output)
                truncated = truncated or did_truncate
                if data:
                    log_parts.append(data)
                    yield ExecutionChunk("stderr", data)
        if truncated:
            suffix = f"\n[output truncated at {config.security_policy.max_output_bytes} bytes]\n"
            log_parts.append(suffix)
            yield ExecutionChunk("stderr", suffix)
        exit_code = int(client.api.exec_inspect(execution_id).get("ExitCode") or 0)
        log_parts.append(f"[exit={exit_code}]\n")
        with self._lock:
            self._execution_logs.append("".join(log_parts))
        yield ExecutionChunk("status", exit_code=exit_code)

    @staticmethod
    def _stream_data(payload: bytes, remaining: int) -> tuple[str, int, bool]:
        if remaining <= 0:
            return "", 0, bool(payload)
        captured = payload[:remaining]
        return (
            captured.decode("utf-8", errors="replace"),
            remaining - len(captured),
            len(payload) > remaining,
        )

    @staticmethod
    def _bounded_outputs(stdout: bytes, stderr: bytes, config: SandboxConfig) -> tuple[str, str]:
        limit = config.security_policy.max_output_bytes
        captured_stdout = stdout[:limit]
        remaining = max(0, limit - len(captured_stdout))
        captured_stderr = stderr[:remaining]
        truncated = len(stdout) + len(stderr) > limit
        suffix = f"\n[output truncated at {limit} bytes]\n" if truncated else ""
        return (
            captured_stdout.decode("utf-8", errors="replace"),
            captured_stderr.decode("utf-8", errors="replace") + suffix,
        )

    def write_file(self, path: str, content: bytes) -> None:
        atomic_write(self._require_workspace(), path, content)

    def read_file(self, path: str) -> bytes:
        return bounded_read(self._require_workspace(), path)

    def snapshot(self, destination: Path) -> SnapshotMetadata:
        """Export the workspace using Docker's container-namespace archive API."""

        container = self._require_container()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        digest = hashlib.sha256()
        try:
            stream, _ = container.get_archive("/workspace")
            with temporary.open("wb") as handle:
                for chunk in stream:
                    digest.update(chunk)
                    handle.write(chunk)
            temporary.replace(destination)
        except (DockerException, OSError) as exc:
            with suppress(FileNotFoundError):
                temporary.unlink()
            raise FileAccessError(f"could not create snapshot: {exc}") from exc
        return SnapshotMetadata(
            destination,
            destination.stat().st_size,
            digest.hexdigest(),
            time.time(),
        )

    def restore(self, source: Path) -> None:
        """Restore a Docker archive containing the `/workspace` directory."""

        container = self._require_container()
        try:
            with source.open("rb") as handle:
                if not container.put_archive("/", handle.read()):
                    raise FileAccessError("Docker rejected the workspace snapshot")
        except FileAccessError:
            raise
        except (DockerException, OSError) as exc:
            raise FileAccessError(f"could not restore snapshot: {exc}") from exc

    def logs(self) -> str:
        with self._lock:
            execution_output = "".join(self._execution_logs)
            container = self._container
        if container is None:
            return execution_output
        try:
            process_output = container.logs(stdout=True, stderr=True).decode(
                "utf-8", errors="replace"
            )
        except (DockerException, OSError):
            process_output = ""
        return process_output + execution_output

    def destroy(self) -> None:
        with self._lock:
            container = self._container
            workspace = self._workspace
            self._container = None
            self._workspace = None
            self._config = None

        if container is not None:
            try:
                container.remove(force=True, v=True)
            except NotFound:
                pass
            except APIError:
                # Destruction is idempotent and best-effort if the daemon vanishes.
                pass
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)

    @staticmethod
    def _format_log(result: ExecutionResult) -> str:
        header = f"$ {result.command}\n"
        status = f"[exit={result.exit_code} duration={result.duration:.3f}s]\n"
        return header + result.stdout + result.stderr + status

    def _cleanup_failed_create(self) -> None:
        container = self._container
        workspace = self._workspace
        self._container = None
        self._workspace = None
        self._config = None
        if container is not None:
            with suppress(DockerException):
                container.remove(force=True, v=True)
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)

    def _require_container(self) -> Container:
        with self._lock:
            if self._container is None:
                raise SandboxDestroyedError("the sandbox has been destroyed")
            return self._container

    def _require_workspace(self) -> Path:
        with self._lock:
            if self._workspace is None:
                raise SandboxDestroyedError("the sandbox has been destroyed")
            return self._workspace

    def _require_config(self) -> SandboxConfig:
        with self._lock:
            if self._config is None:
                raise SandboxDestroyedError("the sandbox has been destroyed")
            return self._config
