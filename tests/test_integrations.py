from __future__ import annotations

import importlib.util

import pytest

from agentnest.exceptions import AgentNestError
from agentnest.integrations import SandboxRunner
from agentnest.integrations.langchain import build_langchain_tool
from agentnest.integrations.smolagents import SandboxExecutor

_HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None


def test_public_adapters_are_importable() -> None:
    # Construction touches Docker, so we only assert the symbols are wired up.
    assert callable(SandboxRunner)
    assert callable(SandboxExecutor)
    assert callable(build_langchain_tool)


@pytest.mark.skipif(_HAS_LANGCHAIN, reason="langchain-core is installed")
def test_langchain_tool_reports_missing_dependency() -> None:
    with pytest.raises(AgentNestError, match="langchain-core"):
        build_langchain_tool()
