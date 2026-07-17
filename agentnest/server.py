"""Optional authenticated API server for remote AgentNest execution."""

from __future__ import annotations

import base64
import tempfile
import threading
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any

from agentnest.exceptions import AgentNestError
from agentnest.policy import NetworkMode, NetworkPolicy, SecurityPolicy
from agentnest.sandbox import Sandbox


def create_app(*, token: str | None = None) -> Any:
    """Create a FastAPI application.

    Install with ``pip install 'agentnest[server]'``. Set a bearer token for
    every deployment reachable beyond a trusted loopback interface.
    """

    try:
        fastapi = import_module("fastapi")
    except ImportError as exc:
        raise AgentNestError("the API server requires: pip install 'agentnest[server]'") from exc

    depends = fastapi.Depends
    fast_api = fastapi.FastAPI
    header = fastapi.Header
    http_exception = fastapi.HTTPException

    app = fast_api(title="AgentNest Runtime API", version="1.0.0")
    sandboxes: dict[str, Sandbox] = {}
    lock = threading.RLock()

    def authorize(authorization: str | None = header(default=None)) -> None:
        if token and authorization != f"Bearer {token}":
            raise http_exception(status_code=401, detail="invalid bearer token")

    def get_sandbox(sandbox_id: str) -> Sandbox:
        with lock:
            sandbox = sandboxes.get(sandbox_id)
        if sandbox is None:
            raise http_exception(status_code=404, detail="sandbox not found")
        return sandbox

    def cleanup() -> None:
        with lock:
            active = tuple(sandboxes.values())
            sandboxes.clear()
        for sandbox in active:
            sandbox.destroy()

    app.add_event_handler("shutdown", cleanup)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/sandboxes", dependencies=[depends(authorize)])
    def create(payload: dict[str, Any]) -> dict[str, str]:
        security = payload.get("security_policy")
        if isinstance(security, dict):
            security_options = dict(security)
            network = security_options.pop("network", {})
            security_options["network"] = NetworkPolicy(
                NetworkMode(network.get("mode", "deny")),
                tuple(network.get("domains", ())),
                tuple(network.get("cidrs", ())),
            )
            payload["security_policy"] = SecurityPolicy(**security_options)
        sandbox = Sandbox(**payload)
        with lock:
            sandboxes[sandbox.id] = sandbox
        return {"id": sandbox.id}

    @app.post("/v1/sandboxes/{sandbox_id}/exec", dependencies=[depends(authorize)])
    def execute(sandbox_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sandbox = get_sandbox(sandbox_id)
        command = payload.pop("command")
        display = payload.pop("display_command", " ".join(command))
        result = sandbox.exec(command, display_command=display, **payload)
        return asdict(result)

    @app.put("/v1/sandboxes/{sandbox_id}/files", dependencies=[depends(authorize)])
    def write_file(sandbox_id: str, payload: dict[str, str]) -> dict[str, bool]:
        get_sandbox(sandbox_id).write_file(
            payload["path"], base64.b64decode(payload["content"], validate=True)
        )
        return {"ok": True}

    @app.post("/v1/sandboxes/{sandbox_id}/files/read", dependencies=[depends(authorize)])
    def read_file(sandbox_id: str, payload: dict[str, str]) -> dict[str, str]:
        content = get_sandbox(sandbox_id).read_file(payload["path"], encoding=None)
        assert isinstance(content, bytes)
        return {"content": base64.b64encode(content).decode()}

    @app.get("/v1/sandboxes/{sandbox_id}/logs", dependencies=[depends(authorize)])
    def logs(sandbox_id: str) -> dict[str, str]:
        return {"logs": get_sandbox(sandbox_id).logs()}

    @app.post("/v1/sandboxes/{sandbox_id}/snapshots", dependencies=[depends(authorize)])
    def snapshot(sandbox_id: str) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(prefix="agentnest-api-", suffix=".tar") as temporary:
            path = Path(temporary.name)
            metadata = get_sandbox(sandbox_id).snapshot(path)
            return {
                "content": base64.b64encode(path.read_bytes()).decode(),
                "sha256": metadata.sha256,
                "created_at": metadata.created_at,
            }

    @app.post(
        "/v1/sandboxes/{sandbox_id}/snapshots/restore",
        dependencies=[depends(authorize)],
    )
    def restore(sandbox_id: str, payload: dict[str, str]) -> dict[str, bool]:
        with tempfile.NamedTemporaryFile(prefix="agentnest-api-", suffix=".tar") as temporary:
            path = Path(temporary.name)
            path.write_bytes(base64.b64decode(payload["content"], validate=True))
            get_sandbox(sandbox_id).restore(path)
            return {"ok": True}

    @app.delete("/v1/sandboxes/{sandbox_id}", dependencies=[depends(authorize)])
    def destroy(sandbox_id: str) -> dict[str, bool]:
        sandbox = get_sandbox(sandbox_id)
        sandbox.destroy()
        with lock:
            sandboxes.pop(sandbox_id, None)
        return {"ok": True}

    return app
