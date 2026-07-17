"""Curated sandbox presets for common agent workloads."""

from __future__ import annotations

from typing import Any

from agentnest.policy import SecurityPolicy
from agentnest.sandbox import Sandbox


def browser_sandbox(
    *,
    timeout: float = 300,
    image: str = "mcr.microsoft.com/playwright/python:v1.52.0-noble",
    security_policy: SecurityPolicy | None = None,
    **kwargs: Any,
) -> Sandbox:
    """Create a Playwright-ready browser sandbox.

    Browser images should be pinned by digest in production. Networking still
    follows the supplied security policy and remains denied by default.
    """

    return Sandbox(
        image,
        timeout,
        security_policy=security_policy or SecurityPolicy(),
        memory=kwargs.pop("memory", "2g"),
        pids=kwargs.pop("pids", 512),
        **kwargs,
    )


def gpu_sandbox(
    image: str,
    *,
    gpus: int = 1,
    timeout: float = 300,
    **kwargs: Any,
) -> Sandbox:
    """Create a Docker sandbox with explicit NVIDIA-compatible GPU requests."""

    if gpus <= 0:
        raise ValueError("gpus must be positive")
    return Sandbox(image, timeout, gpus=gpus, **kwargs)
