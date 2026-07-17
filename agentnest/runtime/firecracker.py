"""Firecracker runtime transport for self-hosted microVM workers."""

from __future__ import annotations

from agentnest.runtime.remote import RemoteRuntime


class FirecrackerRuntime(RemoteRuntime):
    """Connect to an AgentNest worker backed by Firecracker microVMs.

    Firecracker requires a Linux/KVM host and a privileged lifecycle service;
    keeping that service out-of-process preserves the local SDK's security
    boundary. The worker implements the versioned AgentNest Runtime API.
    """
