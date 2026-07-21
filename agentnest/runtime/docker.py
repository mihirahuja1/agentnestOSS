"""Docker implementation of the AgentNest runtime contract."""

from __future__ import annotations

import hashlib
import queue
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.types import DeviceRequest

from agentnest.egress import EgressSidecar, as_domains, egress_labels
from agentnest.exceptions import (
    ExecutionError,
    ExecutionTimeoutError,
    FileAccessError,
    RuntimeNotAvailableError,
    SandboxDestroyedError,
    UnsupportedCapabilityError,
)
from agentnest.filesystem import atomic_write, bounded_read
from agentnest.models import ExecutionChunk, ExecutionResult, SandboxConfig, SnapshotMetadata
from agentnest.runtime.base import RuntimeBackend

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container


_SANDBOX_UID = 65532
_DEFAULT_PATH = "/workspace/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
# Seconds of slack past a command's own deadline before the host-side backstop
# destroys the sandbox. In-container `timeout` should fire first.
_BACKSTOP_GRACE = 15.0
# coreutils `timeout` exit statuses for a deadline breach: 124 when the command
# exits on the initial TERM, 137 (128+9) when it ignores TERM and is KILLed.
_TIMEOUT_EXIT_CODES = frozenset({124, 137})


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
        self._egress: EgressSidecar | None = None
        self._has_timeout = False
        self._owns_image: str | None = None

    def create(self, config: SandboxConfig) -> None:
        with self._lock:
            if self._container is not None:
                raise RuntimeNotAvailableError("this Docker runtime already owns a sandbox")
            config.security_policy.validate_image(config.image)
            workspace = self._prepare_workspace(config)
            self._boot(config, workspace, owns_image=None)

    @staticmethod
    def _prepare_workspace(config: SandboxConfig) -> Path:
        workspace = Path(tempfile.mkdtemp(prefix="agentnest-"))
        # The directory is an unguessable, dedicated mount. World write access lets
        # the fixed non-root container UID use it on Linux without root-side chown.
        workspace.chmod(0o777)
        relative_workdir = config.workdir.removeprefix("/workspace").lstrip("/")
        if relative_workdir:
            workdir_path = workspace / relative_workdir
            workdir_path.mkdir(parents=True, exist_ok=True)
            workdir_path.chmod(0o777)
        return workspace

    def _boot(self, config: SandboxConfig, workspace: Path, *, owns_image: str | None) -> None:
        """Start a container for ``config`` over an already-prepared workspace.

        Shared by :meth:`create` and :meth:`fork`; the latter passes a workspace
        copied from the parent and, when the root filesystem is writable, a
        committed image capturing the parent's out-of-workspace changes.
        """

        self._workspace = workspace
        self._config = config
        self._owns_image = owns_image
        network_policy = config.security_policy.network
        allowlist_mode = network_policy.mode.value == "allowlist"
        if allowlist_mode:
            as_domains(network_policy.domains, network_policy.cidrs)
        # Stamp the lifetime deadline on every managed resource so `agentnest
        # prune` can reap it even if the owning process has crashed.
        deadline_epoch = time.time() + config.timeout
        labels = {"agentnest.managed": "true", "agentnest.deadline": f"{deadline_epoch:.0f}"}
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

            proxy_environment: dict[str, str] = {}
            network_name: str | None = None
            if allowlist_mode:
                sandbox_ref = uuid.uuid4().hex
                self._egress = EgressSidecar(
                    client,
                    sandbox_id=sandbox_ref,
                    domains=network_policy.domains,
                    proxy_image=config.security_policy.egress_proxy_image,
                    labels=egress_labels(labels, sandbox_ref),
                )
                self._egress.start()
                proxy_environment = self._egress.proxy_environment
                network_name = self._egress.network_name

            environment = {
                "HOME": "/workspace/.agentnest-home",
                "PATH": _DEFAULT_PATH,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONUSERBASE": "/workspace/.local",
                **proxy_environment,
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
                "network": network_name,
            }
            self._container = client.containers.create(
                image=config.image,
                command=["sh", "-c", "while :; do sleep 3600; done"],
                detach=True,
                environment=environment,
                working_dir=config.workdir,
                user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
                network_disabled=network_policy.mode.value == "deny",
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
                labels=labels,
                **{key: value for key, value in create_options.items() if value is not None},
            )
            self._container.start()
            self._has_timeout = self._detect_timeout()
        except UnsupportedCapabilityError:
            self._cleanup_failed_create()
            raise
        except (DockerException, OSError) as exc:
            self._cleanup_failed_create()
            raise RuntimeNotAvailableError(f"could not create Docker sandbox: {exc}") from exc

    def fork(self) -> RuntimeBackend:
        """Branch this sandbox into an independent one with copied state."""

        with self._lock:
            container = self._container
            config = self._config
            workspace = self._workspace
            client = self._client
        if container is None or config is None or workspace is None or client is None:
            raise SandboxDestroyedError("the sandbox has been destroyed")
        new_workspace = Path(tempfile.mkdtemp(prefix="agentnest-"))
        try:
            shutil.copytree(workspace, new_workspace, symlinks=True, dirs_exist_ok=True)
            new_workspace.chmod(0o777)
            image = config.image
            owns_image: str | None = None
            if not config.read_only_root:
                # A writable root can hold state outside /workspace; capture it.
                snapshot = container.commit()
                image = str(snapshot.id)
                owns_image = image
        except (DockerException, OSError) as exc:
            shutil.rmtree(new_workspace, ignore_errors=True)
            raise RuntimeNotAvailableError(f"could not fork sandbox: {exc}") from exc
        child = DockerRuntime(client=client, runtime_name=self._runtime_name)
        child._boot(replace(config, image=image), new_workspace, owns_image=owns_image)
        return child

    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        started = time.monotonic()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        exit_code = 0
        for chunk in self._iter_exec(
            command,
            display_command=display_command,
            environment=environment,
            workdir=workdir,
            timeout=timeout,
        ):
            if chunk.stream == "stdout":
                stdout_parts.append(chunk.data)
            elif chunk.stream == "stderr":
                stderr_parts.append(chunk.data)
            else:
                exit_code = chunk.exit_code or 0
        return ExecutionResult(
            command=display_command,
            exit_code=exit_code,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            duration=time.monotonic() - started,
        )

    def stream_exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[ExecutionChunk]:
        """Stream a Docker exec process incrementally."""

        yield from self._iter_exec(
            command,
            display_command=display_command,
            environment=environment,
            workdir=workdir,
            timeout=timeout,
        )

    def _iter_exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None,
        workdir: str | None,
        timeout: float | None,
    ) -> Iterator[ExecutionChunk]:
        """Run one exec, streaming output and enforcing a per-command timeout.

        When the image ships coreutils ``timeout`` (the common case) the command
        is wrapped so a breach kills only that process and leaves the sandbox
        alive and reusable. A host-side deadline is retained as a backstop and,
        for images without ``timeout``, remains the enforcement mechanism -- it
        destroys the sandbox so runaway code cannot keep executing unseen.
        """

        self._require_container()
        config = self._require_config()
        client = self._client
        if client is None:
            raise SandboxDestroyedError("the Docker client is unavailable")
        effective_timeout = timeout if timeout is not None else config.timeout
        run_command, wrapped = self._timeout_wrap(command, effective_timeout)
        backstop = effective_timeout + _BACKSTOP_GRACE if wrapped else effective_timeout
        execution = client.api.exec_create(
            self._require_container().id,
            run_command,
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
        deadline = time.monotonic() + backstop
        log_parts = [f"$ {display_command}\n"]
        remaining_output = config.security_policy.max_output_bytes
        truncated = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.destroy()
                raise ExecutionTimeoutError(
                    f"execution exceeded {backstop:g} seconds; the sandbox was destroyed"
                )
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty as exc:
                self.destroy()
                raise ExecutionTimeoutError(
                    f"execution exceeded {backstop:g} seconds; the sandbox was destroyed"
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
        if wrapped and exit_code in _TIMEOUT_EXIT_CODES:
            log_parts.append("[timed out]\n")
            with self._lock:
                self._execution_logs.append("".join(log_parts))
            raise ExecutionTimeoutError(
                f"execution exceeded {effective_timeout:g} seconds; the process was terminated"
            )
        log_parts.append(f"[exit={exit_code}]\n")
        with self._lock:
            self._execution_logs.append("".join(log_parts))
        yield ExecutionChunk("status", exit_code=exit_code)

    def _timeout_wrap(self, command: list[str], seconds: float) -> tuple[list[str], bool]:
        if not self._has_timeout or seconds <= 0:
            return command, False
        # Send TERM at the deadline for a graceful exit, then KILL 5s later if
        # the process ignores it.
        wrapper = ["timeout", "-k", "5", f"{seconds:g}"]
        return [*wrapper, *command], True

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
            egress = self._egress
            owns_image = self._owns_image
            client = self._client
            self._container = None
            self._workspace = None
            self._config = None
            self._egress = None
            self._owns_image = None

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
        if egress is not None:
            egress.destroy()
        if owns_image is not None and client is not None:
            # Remove the committed image this fork created once its container is gone.
            with suppress(DockerException):
                client.images.remove(owns_image, force=True)

    def _detect_timeout(self) -> bool:
        """Whether the image provides coreutils ``timeout`` for process-level kills."""

        container = self._container
        if container is None:
            return False
        try:
            result = container.exec_run(
                ["sh", "-c", "command -v timeout >/dev/null 2>&1"],
                user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
            )
        except (DockerException, OSError):
            return False
        return result.exit_code == 0

    def _cleanup_failed_create(self) -> None:
        container = self._container
        workspace = self._workspace
        egress = self._egress
        owns_image = self._owns_image
        client = self._client
        self._container = None
        self._workspace = None
        self._config = None
        self._egress = None
        self._owns_image = None
        if container is not None:
            with suppress(DockerException):
                container.remove(force=True, v=True)
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        if egress is not None:
            egress.destroy()
        if owns_image is not None and client is not None:
            with suppress(DockerException):
                client.images.remove(owns_image, force=True)

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
