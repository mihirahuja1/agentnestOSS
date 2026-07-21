"""Adversarial tests for the host-side filesystem and redaction primitives.

Each test *attempts* an escape and asserts it fails. These run without Docker so
they execute on every commit and double as executable threat-model docs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentnest import Sandbox, Secret
from agentnest.exceptions import FileAccessError
from agentnest.filesystem import atomic_write, bounded_read, normalize_workspace_path
from agentnest.secrets import redact
from tests.fakes import FakeRuntime


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../escape", "a/../../b", "..", ".", "", "a/../../../etc"],
)
def test_absolute_and_traversal_paths_are_rejected(path: str) -> None:
    with pytest.raises(FileAccessError):
        normalize_workspace_path(path)


def test_write_refuses_to_follow_a_symlink_out_of_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("original")
    os.symlink(secret, root / "link")

    # Writing "link" must not follow the symlink and clobber the outside file.
    atomic_write(root, "link", b"attacker")
    assert secret.read_text() == "original"
    assert (root / "link").read_bytes() == b"attacker"
    assert not (root / "link").is_symlink()


def test_read_refuses_to_follow_a_symlink_out_of_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, root / "link")

    with pytest.raises(FileAccessError):
        bounded_read(root, "link")


def test_read_refuses_a_symlinked_parent_directory(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("loot")
    os.symlink(outside, root / "escape")

    with pytest.raises(FileAccessError):
        bounded_read(root, "escape/loot.txt")


def test_read_enforces_a_size_limit(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "big.bin").write_bytes(b"x" * 2048)
    with pytest.raises(FileAccessError):
        bounded_read(root, "big.bin", max_bytes=1024)


def test_read_refuses_special_files(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    os.mkfifo(root / "pipe")
    with pytest.raises(FileAccessError):
        bounded_read(root, "pipe")


@pytest.mark.parametrize("pattern", ["/abs/glob", "../outside", "a/../../b"])
def test_artifact_patterns_cannot_escape_the_workspace(pattern: str) -> None:
    sandbox = Sandbox(backend=FakeRuntime())
    try:
        with pytest.raises(ValueError, match="workspace"):
            sandbox.artifacts(pattern)
    finally:
        sandbox.destroy()


def test_secret_values_are_redacted_from_output() -> None:
    secrets = {"TOKEN": Secret("hunter2-super-secret")}
    text = "leaking hunter2-super-secret into logs"
    assert "hunter2-super-secret" not in redact(text, secrets)
    assert "[REDACTED]" in redact(text, secrets)


def test_secret_repr_does_not_disclose_the_value() -> None:
    secret = Secret("do-not-print-me")
    assert "do-not-print-me" not in repr(secret)
    assert "do-not-print-me" not in str(secret)
