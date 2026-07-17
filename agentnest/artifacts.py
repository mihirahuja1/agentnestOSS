"""Typed output artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Artifact:
    """A regular file produced in a sandbox workspace."""

    path: str
    size: int
    sha256: str
