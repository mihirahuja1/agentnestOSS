"""Backend-neutral security policy definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NetworkMode(str, Enum):
    """Outbound network policy mode."""

    DENY = "deny"
    ALLOW = "allow"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Network access requested for a sandbox.

    Fine-grained allowlists require a backend that can enforce them. Backends
    must reject unsupported policies rather than widening access.
    """

    mode: NetworkMode = NetworkMode.DENY
    domains: tuple[str, ...] = ()
    cidrs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode is NetworkMode.ALLOWLIST and not (self.domains or self.cidrs):
            raise ValueError("an allowlist policy requires at least one domain or CIDR")
        if self.mode is not NetworkMode.ALLOWLIST and (self.domains or self.cidrs):
            raise ValueError("domains and CIDRs are only valid in allowlist mode")

    @classmethod
    def denied(cls) -> NetworkPolicy:
        return cls(NetworkMode.DENY)

    @classmethod
    def allowed(cls) -> NetworkPolicy:
        return cls(NetworkMode.ALLOW)

    @classmethod
    def allowlist(
        cls, *, domains: tuple[str, ...] = (), cidrs: tuple[str, ...] = ()
    ) -> NetworkPolicy:
        return cls(NetworkMode.ALLOWLIST, domains, cidrs)


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Portable, fail-closed controls applied to sandbox workloads."""

    network: NetworkPolicy = field(default_factory=NetworkPolicy.denied)
    max_output_bytes: int = 10 * 1024 * 1024
    max_file_read_bytes: int = 64 * 1024 * 1024
    allowed_images: tuple[str, ...] = ()
    require_image_digest: bool = False
    seccomp_profile: str | None = None
    apparmor_profile: str | None = None
    rootless: bool = False
    egress_proxy_image: str = "python:3.12-slim"

    def __post_init__(self) -> None:
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if self.max_file_read_bytes <= 0:
            raise ValueError("max_file_read_bytes must be positive")

    def validate_image(self, image: str) -> None:
        """Raise when an image is outside the configured trust policy."""

        if self.require_image_digest and "@sha256:" not in image:
            raise ValueError("security policy requires an image pinned by sha256 digest")
        if self.allowed_images and image not in self.allowed_images:
            raise ValueError(f"image is not allowed by security policy: {image!r}")
