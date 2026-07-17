"""Optional MCP server exposing AgentNest as agent tools."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from agentnest.exceptions import AgentNestError
from agentnest.sandbox import Sandbox


def create_mcp_server() -> Any:
    """Create an MCP server with sandbox lifecycle and execution tools."""

    try:
        fast_mcp = import_module("mcp.server.fastmcp").FastMCP
    except ImportError as exc:
        raise AgentNestError("MCP support requires: pip install 'agentnest[mcp]'") from exc

    server = fast_mcp("AgentNest")
    sandboxes: dict[str, Sandbox] = {}

    @server.tool()
    def create_sandbox(
        runtime: str = "python:3.12-slim",
        timeout: float = 300,
        network_enabled: bool = False,
    ) -> dict[str, str]:
        """Create an isolated execution sandbox."""

        sandbox = Sandbox(runtime, timeout, network_enabled=network_enabled)
        sandboxes[sandbox.id] = sandbox
        return {"sandbox_id": sandbox.id}

    @server.tool()
    def exec_python(sandbox_id: str, code: str, timeout: float | None = None) -> dict[str, Any]:
        """Execute Python in an existing sandbox."""

        result = sandboxes[sandbox_id].exec_python(code, timeout=timeout)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": result.duration,
        }

    @server.tool()
    def exec_shell(sandbox_id: str, script: str, timeout: float | None = None) -> dict[str, Any]:
        """Execute a shell script in an existing sandbox."""

        result = sandboxes[sandbox_id].exec_shell(script, timeout=timeout)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": result.duration,
        }

    @server.tool()
    def write_file(sandbox_id: str, path: str, content: str) -> dict[str, bool]:
        """Write a UTF-8 text file in a sandbox workspace."""

        sandboxes[sandbox_id].write_file(path, content)
        return {"ok": True}

    @server.tool()
    def read_file(sandbox_id: str, path: str) -> str:
        """Read a UTF-8 text file from a sandbox workspace."""

        result = sandboxes[sandbox_id].read_file(path)
        assert isinstance(result, str)
        return result

    @server.tool()
    def destroy_sandbox(sandbox_id: str) -> dict[str, bool]:
        """Destroy a sandbox and release its resources."""

        sandbox = sandboxes.pop(sandbox_id)
        sandbox.destroy()
        return {"ok": True}

    return server
