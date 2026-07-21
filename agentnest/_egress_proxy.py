"""Standalone allowlisting HTTP CONNECT proxy for sandbox egress.

This module runs inside a dedicated sidecar container that has the only route to
the outside world. The sandbox container is placed on an ``internal`` Docker
network with no direct internet access and is pointed at this proxy through the
standard ``HTTP_PROXY``/``HTTPS_PROXY`` variables. Every tunnel request is
checked against a domain allowlist before a single byte is forwarded, so code in
the sandbox can reach ``pypi.org`` while it provably cannot phone home anywhere
else.

The file is intentionally dependency-free: it is mounted read-only into a stock
``python`` image and executed with ``python _egress_proxy.py``. The matching
logic is also imported in-process by the test suite, so keep it stdlib-only.
"""

from __future__ import annotations

import contextlib
import os
import select
import socket
import sys
import threading
from collections.abc import Iterable

BUFFER_SIZE = 65536
DEFAULT_PORT = 8080
CONNECT_TIMEOUT = 10.0


def normalize_patterns(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated allowlist into lowercase host patterns."""

    patterns = []
    for item in raw.split(","):
        pattern = item.strip().lower().rstrip(".")
        if pattern:
            patterns.append(pattern)
    return tuple(patterns)


def host_allowed(host: str, patterns: Iterable[str]) -> bool:
    """Return whether ``host`` matches an exact or subdomain allowlist entry.

    A pattern matches the host itself and any subdomain of it: ``pypi.org``
    allows ``pypi.org`` and ``files.pypi.org`` but never ``notpypi.org`` or an
    unrelated ``evil.com``. Matching is case-insensitive and ignores a trailing
    dot on the requested host.
    """

    candidate = host.strip().lower().rstrip(".")
    if not candidate:
        return False
    for pattern in patterns:
        if not pattern:
            continue
        if candidate == pattern or candidate.endswith("." + pattern):
            return True
    return False


def _pump(source: socket.socket, destination: socket.socket) -> None:
    sockets = [source, destination]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored:
                break
            if not readable:
                continue
            for ready in readable:
                data = ready.recv(BUFFER_SIZE)
                if not data:
                    return
                target = destination if ready is source else source
                target.sendall(data)
    except OSError:
        return


def _read_request_line(connection: socket.socket) -> tuple[str, bytes]:
    buffer = b""
    while b"\r\n" not in buffer:
        chunk = connection.recv(BUFFER_SIZE)
        if not chunk:
            break
        buffer += chunk
        if len(buffer) > 65536:
            break
    line, _, rest = buffer.partition(b"\r\n")
    return line.decode("latin-1", errors="replace"), rest


def _deny(connection: socket.socket, code: str, host: str) -> None:
    body = f"AgentNest egress policy blocked {host}".encode()
    connection.sendall(
        f"HTTP/1.1 {code}\r\nContent-Length: {len(body)}\r\n"
        "Content-Type: text/plain\r\nConnection: close\r\n\r\n".encode()
        + body
    )


def _handle(connection: socket.socket, patterns: tuple[str, ...]) -> None:
    try:
        connection.settimeout(CONNECT_TIMEOUT)
        request_line, _ = _read_request_line(connection)
        parts = request_line.split(" ")
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            # Only tunnelled HTTPS (and proxied TCP) is supported. Plain
            # forward-proxy HTTP is refused so nothing bypasses the allowlist.
            _deny(connection, "405 Method Not Allowed", parts[1] if len(parts) > 1 else "?")
            return
        authority = parts[1]
        host, _, port_text = authority.rpartition(":")
        if not host:
            host, port_text = authority, "443"
        try:
            port = int(port_text)
        except ValueError:
            _deny(connection, "400 Bad Request", authority)
            return
        if not host_allowed(host, patterns):
            print(f"deny {host}:{port}", file=sys.stderr, flush=True)
            _deny(connection, "403 Forbidden", host)
            return
        try:
            upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        except OSError:
            _deny(connection, "502 Bad Gateway", host)
            return
        print(f"allow {host}:{port}", file=sys.stderr, flush=True)
        connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        connection.settimeout(None)
        upstream.settimeout(None)
        with upstream:
            _pump(connection, upstream)
    except OSError:
        return
    finally:
        with contextlib.suppress(OSError):
            connection.close()


def serve(patterns: tuple[str, ...], port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(128)
    print(f"agentnest egress proxy listening on {port}; allow={','.join(patterns)}", flush=True)
    while True:
        connection, _ = listener.accept()
        thread = threading.Thread(target=_handle, args=(connection, patterns), daemon=True)
        thread.start()


def main() -> None:
    patterns = normalize_patterns(os.environ.get("AGENTNEST_ALLOW", ""))
    port = int(os.environ.get("AGENTNEST_PROXY_PORT", DEFAULT_PORT))
    serve(patterns, port)


if __name__ == "__main__":
    main()
