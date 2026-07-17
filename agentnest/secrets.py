"""Secret values and deterministic log redaction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, repr=False)
class Secret:
    """A value that never reveals itself through repr or str."""

    value: str

    def __repr__(self) -> str:
        return "Secret('********')"

    def __str__(self) -> str:
        return "********"


def reveal_environment(environment: Mapping[str, str | Secret]) -> dict[str, str]:
    """Resolve secret values immediately before backend execution."""

    return {
        key: value.value if isinstance(value, Secret) else value
        for key, value in environment.items()
    }


def redact(text: str, secrets: Mapping[str, str | Secret]) -> str:
    """Replace known non-empty secret values in captured output."""

    redacted = text
    values = sorted(
        (value.value for value in secrets.values() if isinstance(value, Secret) and value.value),
        key=len,
        reverse=True,
    )
    for value in values:
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted
