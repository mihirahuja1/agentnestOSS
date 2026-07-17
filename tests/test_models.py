from __future__ import annotations

import pytest

from agentnest import ExecutionError, ExecutionResult, ResourceLimits
from agentnest.models import SandboxConfig


def test_execution_result_check_returns_success() -> None:
    result = ExecutionResult("true", 0, "", "", 0.1)
    assert result.ok
    assert result.check() is result


def test_execution_result_check_raises_with_stderr() -> None:
    result = ExecutionResult("false", 7, "", "bad", 0.1)
    with pytest.raises(ExecutionError, match="status 7: bad"):
        result.check()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"cpus": 0}, "cpus"),
        ({"pids": 0}, "pids"),
        ({"memory": 0}, "memory"),
        ({"memory": ""}, "memory"),
    ],
)
def test_resource_limits_validate(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ResourceLimits(**kwargs)  # type: ignore[arg-type]


def test_config_environment_is_copied_and_read_only() -> None:
    environment = {"TOKEN": "safe"}
    config = SandboxConfig("python:3.12", 30, environment)
    environment["TOKEN"] = "changed"
    assert config.environment["TOKEN"] == "safe"
    with pytest.raises(TypeError):
        config.environment["TOKEN"] = "nope"  # type: ignore[index]
