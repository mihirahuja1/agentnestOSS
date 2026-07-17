"""Optional Kubernetes runtime backend."""

from __future__ import annotations

import base64
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from importlib import import_module
from typing import Any

from agentnest.exceptions import (
    AgentNestError,
    ExecutionError,
    ExecutionTimeoutError,
    RuntimeNotAvailableError,
    SandboxDestroyedError,
    UnsupportedCapabilityError,
)
from agentnest.filesystem import normalize_workspace_path
from agentnest.models import ExecutionResult, SandboxConfig
from agentnest.policy import NetworkMode
from agentnest.runtime.base import RuntimeBackend


class KubernetesRuntime(RuntimeBackend):
    """Run a sandbox as a locked-down Kubernetes Pod and ephemeral workspace."""

    def __init__(
        self,
        *,
        namespace: str = "default",
        context: str | None = None,
        runtime_class_name: str | None = None,
    ) -> None:
        self._namespace = namespace
        self._context = context
        self._runtime_class_name = runtime_class_name
        self._pod_name: str | None = None
        self._core: Any = None
        self._networking: Any = None
        self._stream: Any = None
        self._config: SandboxConfig | None = None
        self._execution_logs: list[str] = []

    def create(self, config: SandboxConfig) -> None:
        if config.security_policy.network.domains:
            raise UnsupportedCapabilityError(
                "Kubernetes NetworkPolicy cannot securely enforce DNS allowlists; use CIDRs"
            )
        try:
            client = import_module("kubernetes.client")
            kube_config = import_module("kubernetes.config")
            config_exception = import_module("kubernetes.config.config_exception")
            stream_module = import_module("kubernetes.stream")
        except ImportError as exc:
            raise AgentNestError(
                "Kubernetes support requires: pip install 'agentnest[kubernetes]'"
            ) from exc

        try:
            try:
                kube_config.load_incluster_config()
            except config_exception.ConfigException:
                kube_config.load_kube_config(context=self._context)
            self._core = client.CoreV1Api()
            self._networking = client.NetworkingV1Api()
            self._stream = stream_module.stream
            self._config = config
            self._pod_name = f"agentnest-{uuid.uuid4().hex[:12]}"
            self._core.create_namespaced_pod(self._namespace, self._pod_manifest(config))
            self._create_network_policy(config)
            self._wait_until_running(config.timeout)
        except AgentNestError:
            self.destroy()
            raise
        except Exception as exc:
            self.destroy()
            raise RuntimeNotAvailableError(f"could not create Kubernetes sandbox: {exc}") from exc

    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        pod_name = self._id()
        config = self._require_config()
        effective_timeout = timeout or config.timeout
        if environment or workdir:
            exports = " ".join(
                f"{key}={_shell_quote(value)}" for key, value in (environment or {}).items()
            )
            directory = _shell_quote(workdir or config.workdir)
            rendered = " ".join(_shell_quote(part) for part in command)
            command = ["sh", "-c", f"cd {directory} && env {exports} {rendered}"]
        started = time.monotonic()
        try:
            response = self._stream(
                self._core.connect_get_namespaced_pod_exec,
                pod_name,
                self._namespace,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            stdout: list[str] = []
            stderr: list[str] = []
            while response.is_open():
                response.update(timeout=1)
                if response.peek_stdout():
                    stdout.append(response.read_stdout())
                if response.peek_stderr():
                    stderr.append(response.read_stderr())
                if time.monotonic() - started > effective_timeout:
                    response.close()
                    self.destroy()
                    raise ExecutionTimeoutError(
                        f"execution exceeded {effective_timeout:g} seconds; "
                        "the sandbox was destroyed"
                    )
            exit_code = int(response.returncode or 0)
        except ExecutionTimeoutError:
            raise
        except Exception as exc:
            raise ExecutionError(f"Kubernetes execution failed: {exc}") from exc
        stdout_text, stderr_text = self._bounded_outputs(
            "".join(stdout), "".join(stderr), config.security_policy.max_output_bytes
        )
        result = ExecutionResult(
            display_command,
            exit_code,
            stdout_text,
            stderr_text,
            time.monotonic() - started,
        )
        self._execution_logs.append(
            f"$ {display_command}\n{result.stdout}{result.stderr}[exit={exit_code}]\n"
        )
        return result

    @staticmethod
    def _bounded_outputs(stdout: str, stderr: str, limit: int) -> tuple[str, str]:
        stdout_bytes = stdout.encode()
        stderr_bytes = stderr.encode()
        captured_stdout = stdout_bytes[:limit]
        remaining = max(0, limit - len(captured_stdout))
        captured_stderr = stderr_bytes[:remaining]
        truncated = len(stdout_bytes) + len(stderr_bytes) > limit
        suffix = f"\n[output truncated at {limit} bytes]\n" if truncated else ""
        return (
            captured_stdout.decode(errors="replace"),
            captured_stderr.decode(errors="replace") + suffix,
        )

    def write_file(self, path: str, content: bytes) -> None:
        path = normalize_workspace_path(path)
        encoded = base64.b64encode(content).decode()
        code = (
            "import base64,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
            "p.parent.mkdir(parents=True,exist_ok=True); "
            "p.write_bytes(base64.b64decode(sys.argv[2]))"
        )
        self.exec(
            ["python", "-c", code, f"/workspace/{path}", encoded],
            display_command=f"write {path}",
        ).check()

    def read_file(self, path: str) -> bytes:
        path = normalize_workspace_path(path)
        code = (
            "import base64,pathlib,sys; "
            "print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())"
        )
        result = self.exec(
            ["python", "-c", code, f"/workspace/{path}"], display_command=f"read {path}"
        ).check()
        return base64.b64decode(result.stdout.strip(), validate=True)

    def logs(self) -> str:
        pod_logs = ""
        if self._pod_name is not None:
            with suppress(Exception):
                pod_logs = self._core.read_namespaced_pod_log(self._pod_name, self._namespace)
        return pod_logs + "".join(self._execution_logs)

    def destroy(self) -> None:
        pod_name = self._pod_name
        self._pod_name = None
        self._config = None
        if pod_name is None or self._core is None:
            return
        with suppress(Exception):
            self._core.delete_namespaced_pod(
                pod_name,
                self._namespace,
                grace_period_seconds=0,
                propagation_policy="Background",
            )
        if self._networking is not None:
            with suppress(Exception):
                self._networking.delete_namespaced_network_policy(pod_name, self._namespace)

    def _pod_manifest(self, config: SandboxConfig) -> dict[str, Any]:
        limits: dict[str, str] = {
            "memory": str(config.limits.memory),
            "cpu": str(config.limits.cpus),
        }
        if config.limits.gpus:
            limits["nvidia.com/gpu"] = str(config.limits.gpus)
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": self._id(),
                "labels": {"agentnest.managed": "true", "agentnest.id": self._id()},
            },
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "runtimeClassName": self._runtime_class_name,
                "securityContext": {
                    "runAsNonRoot": True,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "sandbox",
                        "image": config.image,
                        "command": ["sh", "-c", "while :; do sleep 3600; done"],
                        "workingDir": config.workdir,
                        "env": [
                            {"name": key, "value": value}
                            for key, value in config.environment.items()
                        ],
                        "resources": {"limits": limits, "requests": limits},
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": config.read_only_root,
                            "runAsUser": 65532,
                            "runAsGroup": 65532,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [
                            {"name": "workspace", "mountPath": "/workspace"},
                            {"name": "tmp", "mountPath": "/tmp"},
                        ],
                    }
                ],
                "volumes": [
                    {"name": "workspace", "emptyDir": {"sizeLimit": "2Gi"}},
                    {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}},
                ],
            },
        }

    def _create_network_policy(self, config: SandboxConfig) -> None:
        policy = config.security_policy.network
        if policy.mode is NetworkMode.ALLOW:
            return
        egress = []
        if policy.mode is NetworkMode.ALLOWLIST:
            egress = [{"to": [{"ipBlock": {"cidr": cidr}} for cidr in policy.cidrs]}]
        manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": self._id()},
            "spec": {
                "podSelector": {"matchLabels": {"agentnest.id": self._id()}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],
                "egress": egress,
            },
        }
        self._networking.create_namespaced_network_policy(self._namespace, manifest)

    def _wait_until_running(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pod = self._core.read_namespaced_pod(self._id(), self._namespace)
            phase = pod.status.phase
            if phase == "Running":
                return
            if phase in {"Failed", "Succeeded"}:
                raise RuntimeNotAvailableError(f"sandbox pod entered terminal phase {phase}")
            time.sleep(0.25)
        raise RuntimeNotAvailableError("timed out waiting for sandbox pod to start")

    def _id(self) -> str:
        if self._pod_name is None:
            raise SandboxDestroyedError("the Kubernetes sandbox has been destroyed")
        return self._pod_name

    def _require_config(self) -> SandboxConfig:
        if self._config is None:
            raise SandboxDestroyedError("the Kubernetes sandbox has been destroyed")
        return self._config


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
