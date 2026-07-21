from __future__ import annotations

import pytest

from agentnest import Sandbox, UnsupportedCapabilityError
from agentnest.runtime.base import RuntimeBackend
from tests.fakes import FakeRuntime


class ForkableFake(FakeRuntime):
    def fork(self) -> RuntimeBackend:
        child = ForkableFake()
        child.config = self.config
        child.files = dict(self.files)
        return child


def test_fork_creates_independent_sandbox() -> None:
    parent = Sandbox(backend=ForkableFake())
    parent.write_file("state.txt", "parent")
    child = parent.fork()
    try:
        assert child.id != parent.id
        assert child.read_file("state.txt") == "parent"
        # Divergence: a later write on the child is invisible to the parent.
        child.write_file("state.txt", "child")
        assert child.read_file("state.txt") == "child"
        assert parent.read_file("state.txt") == "parent"
    finally:
        child.destroy()
        parent.destroy()


def test_fork_is_rejected_when_backend_cannot_fork() -> None:
    sandbox = Sandbox(backend=FakeRuntime())
    with pytest.raises(UnsupportedCapabilityError, match="fork"):
        sandbox.fork()
    sandbox.destroy()
