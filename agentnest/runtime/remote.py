"""HTTP remote-execution backend for dedicated AgentNest hosts."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from agentnest.exceptions import ExecutionError, RuntimeNotAvailableError, SandboxDestroyedError
from agentnest.models import ExecutionResult, SandboxConfig, SnapshotMetadata
from agentnest.runtime.base import RuntimeBackend


class RemoteRuntime(RuntimeBackend):
    """Use an AgentNest API server as a runtime backend."""

    def __init__(self, url: str, *, token: str | None = None, request_timeout: float = 30) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._request_timeout = request_timeout
        self._sandbox_id: str | None = None

    def create(self, config: SandboxConfig) -> None:
        response = self._request(
            "POST",
            "/v1/sandboxes",
            {
                "runtime": config.image,
                "timeout": config.timeout,
                "environment": dict(config.environment),
                "workdir": config.workdir,
                "network_enabled": config.network_enabled,
                "memory": config.limits.memory,
                "cpus": config.limits.cpus,
                "pids": config.limits.pids,
                "gpus": config.limits.gpus,
                "security_policy": {
                    "network": {
                        "mode": config.security_policy.network.mode.value,
                        "domains": config.security_policy.network.domains,
                        "cidrs": config.security_policy.network.cidrs,
                    },
                    "max_output_bytes": config.security_policy.max_output_bytes,
                    "max_file_read_bytes": config.security_policy.max_file_read_bytes,
                    "allowed_images": config.security_policy.allowed_images,
                    "require_image_digest": config.security_policy.require_image_digest,
                    "seccomp_profile": config.security_policy.seccomp_profile,
                    "apparmor_profile": config.security_policy.apparmor_profile,
                    "rootless": config.security_policy.rootless,
                },
            },
        )
        self._sandbox_id = str(response["id"])

    def exec(
        self,
        command: list[str],
        *,
        display_command: str,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        response = self._request(
            "POST",
            f"/v1/sandboxes/{self._id()}/exec",
            {
                "command": command,
                "display_command": display_command,
                "environment": dict(environment or {}),
                "workdir": workdir,
                "timeout": timeout,
            },
        )
        return ExecutionResult(**response)

    def write_file(self, path: str, content: bytes) -> None:
        self._request(
            "PUT",
            f"/v1/sandboxes/{self._id()}/files",
            {"path": path, "content": base64.b64encode(content).decode()},
        )

    def read_file(self, path: str) -> bytes:
        response = self._request("POST", f"/v1/sandboxes/{self._id()}/files/read", {"path": path})
        return base64.b64decode(response["content"], validate=True)

    def logs(self) -> str:
        return str(self._request("GET", f"/v1/sandboxes/{self._id()}/logs")["logs"])

    def snapshot(self, destination: Path) -> SnapshotMetadata:
        response = self._request("POST", f"/v1/sandboxes/{self._id()}/snapshots")
        payload = base64.b64decode(response["content"], validate=True)
        destination.write_bytes(payload)
        return SnapshotMetadata(
            destination,
            len(payload),
            str(response["sha256"]),
            float(response.get("created_at", time.time())),
        )

    def restore(self, source: Path) -> None:
        self._request(
            "POST",
            f"/v1/sandboxes/{self._id()}/snapshots/restore",
            {"content": base64.b64encode(source.read_bytes()).decode()},
        )

    def destroy(self) -> None:
        if self._sandbox_id is None:
            return
        sandbox_id = self._sandbox_id
        self._sandbox_id = None
        with suppress(RuntimeNotAvailableError):
            self._request("DELETE", f"/v1/sandboxes/{sandbox_id}")

    def _id(self) -> str:
        if self._sandbox_id is None:
            raise SandboxDestroyedError("the remote sandbox has been destroyed")
        return self._sandbox_id

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(self._url + path, body, headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
                result: dict[str, Any] = json.loads(response.read())
                return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ExecutionError(f"remote AgentNest request failed ({exc.code}): {detail}") from exc
        except (OSError, ValueError) as exc:
            raise RuntimeNotAvailableError(
                f"remote AgentNest server is unavailable: {exc}"
            ) from exc
