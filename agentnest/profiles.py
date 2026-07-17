"""Load reusable sandbox profiles from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from agentnest.exceptions import AgentNestError
from agentnest.policy import NetworkMode, NetworkPolicy, SecurityPolicy


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    """Validated constructor arguments loaded from a profile file."""

    name: str
    options: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path, name: str = "default") -> SandboxProfile:
        try:
            yaml = import_module("yaml")
        except ImportError as exc:
            raise AgentNestError(
                "YAML profiles require: pip install 'agentnest[profiles]'"
            ) from exc
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or name not in document:
            raise ValueError(f"profile does not exist: {name!r}")
        raw = document[name]
        if not isinstance(raw, dict):
            raise ValueError("profile contents must be a mapping")
        options = dict(raw)
        network = options.pop("network", None)
        if network is not None:
            if not isinstance(network, dict):
                raise ValueError("network profile must be a mapping")
            policy = NetworkPolicy(
                NetworkMode(network.get("mode", "deny")),
                tuple(network.get("domains", ())),
                tuple(network.get("cidrs", ())),
            )
            options["security_policy"] = SecurityPolicy(network=policy)
        return cls(name, options)
