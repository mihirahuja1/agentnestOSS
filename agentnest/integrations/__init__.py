"""Adapters that expose an AgentNest sandbox as a tool for agent frameworks.

The core is :class:`SandboxRunner`, a framework-neutral, sandbox-backed Python
runner with an optional persistent session. Thin adapters wrap it for specific
frameworks so the security boundary is identical no matter who calls it.
"""

from __future__ import annotations

from agentnest.integrations.base import SandboxRunner

__all__ = ["SandboxRunner"]
