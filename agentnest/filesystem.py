"""Race-safe filesystem primitives for host-mounted sandbox workspaces."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from agentnest.exceptions import FileAccessError

DEFAULT_MAX_READ_BYTES = 64 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise FileAccessError("workspace paths must be relative")
    parts = candidate.parts
    if not parts or parts == (".",) or any(part in {"", ".", ".."} for part in parts):
        raise FileAccessError(f"invalid workspace file path: {relative_path!r}")
    return parts


def resolve_workspace_path(root: Path, relative_path: str) -> Path:
    """Resolve a user path while preventing absolute paths and traversal.

    This helper is useful for validation and diagnostics. Reads and writes use
    directory-relative file descriptors as well, preventing symlink swap races.
    """

    candidate = Path(*_relative_parts(relative_path))
    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve(strict=False)
    if root_resolved not in resolved.parents:
        raise FileAccessError(f"path escapes the sandbox workspace: {relative_path!r}")
    return resolved


def _open_parent(root: Path, parts: tuple[str, ...], *, create: bool) -> tuple[int, str]:
    descriptor = os.open(root, _DIRECTORY_FLAGS)
    try:
        for component in parts[:-1]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(component, mode=0o777, dir_fd=descriptor)
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if create:
                os.fchmod(descriptor, 0o777)
        return descriptor, parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def atomic_write(root: Path, relative_path: str, content: bytes) -> None:
    """Atomically write a workspace file without following workspace symlinks."""

    parts = _relative_parts(relative_path)
    temporary = f".agentnest-{secrets.token_hex(12)}"
    parent_descriptor: int | None = None
    try:
        parent_descriptor, filename = _open_parent(root, parts, create=True)
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o666,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
        os.replace(
            temporary,
            filename,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
    except OSError as exc:
        if parent_descriptor is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent_descriptor)
        raise FileAccessError(f"could not write {relative_path!r}: {exc}") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def bounded_read(root: Path, relative_path: str, max_bytes: int = DEFAULT_MAX_READ_BYTES) -> bytes:
    """Read a regular workspace file safely up to a defensive size limit."""

    parts = _relative_parts(relative_path)
    parent_descriptor: int | None = None
    try:
        parent_descriptor, filename = _open_parent(root, parts, create=False)
        file_descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_descriptor)
        with os.fdopen(file_descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise FileAccessError(f"workspace path is not a regular file: {relative_path!r}")
            if metadata.st_size > max_bytes:
                raise FileAccessError(f"workspace file exceeds the {max_bytes}-byte read limit")
            payload = handle.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise FileAccessError(f"workspace file exceeds the {max_bytes}-byte read limit")
            return payload
    except FileAccessError:
        raise
    except OSError as exc:
        raise FileAccessError(f"could not read {relative_path!r}: {exc}") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
