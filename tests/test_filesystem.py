from __future__ import annotations

from pathlib import Path

import pytest

from agentnest.exceptions import FileAccessError
from agentnest.filesystem import atomic_write, bounded_read, resolve_workspace_path


def test_atomic_write_and_bounded_read(tmp_path: Path) -> None:
    atomic_write(tmp_path, "nested/data.bin", b"payload")
    assert bounded_read(tmp_path, "nested/data.bin") == b"payload"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", ".", "nested/../../secret"])
def test_resolve_rejects_workspace_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(FileAccessError):
        resolve_workspace_path(tmp_path, path)


def test_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileAccessError):
        resolve_workspace_path(tmp_path, "link/secret")


def test_file_operations_reject_symlink_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-operations"
    outside.mkdir(exist_ok=True)
    (outside / "secret").write_bytes(b"host")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(FileAccessError):
        atomic_write(tmp_path, "link/secret", b"sandbox")
    with pytest.raises(FileAccessError):
        bounded_read(tmp_path, "link/secret")
    assert (outside / "secret").read_bytes() == b"host"


def test_bounded_read_rejects_large_file(tmp_path: Path) -> None:
    (tmp_path / "large").write_bytes(b"1234")
    with pytest.raises(FileAccessError, match="exceeds"):
        bounded_read(tmp_path, "large", max_bytes=3)
