"""Docker implementation of the AgentNest runtime contract."""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from agentnest.exceptions import ExecutionError, RuntimeNotAvailableError, SandboxDestroyedError
from agentnest.execution import run_with_timeout
from agentnest.filesystem import atomic_write, bounded_read
from agentnest.models import ExecutionResult, SandboxConfig
from agentnest.runtime.base import RuntimeBackend

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container


_SANDBOX_UID = 65532
_DEFAULT_PATH = "/workspace/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"


class DockerRuntime(RuntimeBackend):
    """Run one sandbox in a hardened Docker container."""

    def __init__(self, client: DockerClient | None = None) -> None:
        self._client = client
        self._container: Container | None = None
        self._workspace: Path | None = None
        self._config: SandboxConfig | None = None
        self._execution_logs: list[str] = []
        self._lock = threading.RLock()

    def create(self, config: SandboxConfig) -> None:
        with self._lock:
            if self._container is not None:
                raise RuntimeNotAvailableError("this Docker runtime already owns a sandbox")

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
                self._container = client.containers.create(
                    image=config.image,
                    command=["sh", "-c", "while :; do sleep 3600; done"],
                    detach=True,
                    environment=environment,
                    working_dir=config.workdir,
                    user=f"{_SANDBOX_UID}:{_SANDBOX_UID}",
                    network_disabled=not config.network_enabled,
                    read_only=config.read_only_root,
                    privileged=False,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
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
                )
                self._container.start()
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
        result = ExecutionResult(
            command=display_command,
            exit_code=int(response.exit_code),
            stdout=(stdout_raw or b"").decode("utf-8", errors="replace"),
            stderr=(stderr_raw or b"").decode("utf-8", errors="replace"),
            duration=time.monotonic() - started,
        )
        with self._lock:
            self._execution_logs.append(self._format_log(result))
        return result

    def write_file(self, path: str, content: bytes) -> None:
        atomic_write(self._require_workspace(), path, content)

    def read_file(self, path: str) -> bytes:
        return bounded_read(self._require_workspace(), path)

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
