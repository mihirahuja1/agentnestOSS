"""Command-line interface for AgentNest."""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

from agentnest import __version__
from agentnest.registry import registry
from agentnest.sandbox import Sandbox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentnest", description="Secure AI agent execution")
    parser.add_argument("--version", action="version", version=f"AgentNest {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run Python code or a .py file in a new sandbox")
    run.add_argument("code", help="Python source, or a path to a .py file")
    _sandbox_arguments(run)

    shell = subcommands.add_parser("shell", help="run a shell script in a new sandbox")
    shell.add_argument("script")
    _sandbox_arguments(shell)

    subcommands.add_parser("demo", help="run a self-contained sandbox demo (no arguments needed)")

    prune = subcommands.add_parser("prune", help="remove managed sandboxes left by crashes")
    prune.add_argument(
        "--all",
        action="store_true",
        dest="force_all",
        help="remove every managed sandbox, not only expired ones",
    )

    subcommands.add_parser("backends", help="list discovered runtime backends")
    subcommands.add_parser("doctor", help="check the local runtime environment")

    serve = subcommands.add_parser("serve", help="start the remote runtime API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    subcommands.add_parser("mcp", help="start the AgentNest MCP server")
    return parser


def _sandbox_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--image", default="python:3.12-slim")
    parser.add_argument("--backend", default="docker")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--memory", default="512m")
    parser.add_argument("--cpus", type=float, default=1.0)


def _sandbox_options(arguments: argparse.Namespace) -> dict[str, Any]:
    return {
        "runtime": arguments.image,
        "backend": arguments.backend,
        "timeout": arguments.timeout,
        "network_enabled": arguments.network,
        "memory": arguments.memory,
        "cpus": arguments.cpus,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "backends":
        print("\n".join(registry.names()))
        return 0
    if arguments.command == "doctor":
        return _doctor()
    if arguments.command == "serve":
        api_token = os.environ.get("AGENTNEST_API_TOKEN")
        if arguments.host not in {"127.0.0.1", "localhost", "::1"} and not api_token:
            print(
                "Refusing a non-loopback API without AGENTNEST_API_TOKEN",
                file=sys.stderr,
            )
            return 2
        try:
            uvicorn = import_module("uvicorn")
        except ImportError:
            print("Install server support with: pip install 'agentnest[server]'", file=sys.stderr)
            return 2
        from agentnest.server import create_app

        uvicorn.run(
            create_app(token=api_token),
            host=arguments.host,
            port=arguments.port,
        )
        return 0
    if arguments.command == "mcp":
        from agentnest.mcp_server import create_mcp_server

        create_mcp_server().run()
        return 0
    if arguments.command == "prune":
        return _prune(arguments.force_all)
    if arguments.command == "demo":
        return _demo()

    with Sandbox(**_sandbox_options(arguments)) as sandbox:
        if arguments.command == "run":
            candidate = Path(arguments.code)
            if arguments.code.endswith(".py") and candidate.is_file():
                code = candidate.read_text(encoding="utf-8")
            else:
                code = arguments.code
            result = sandbox.exec_python(code)
        else:
            result = sandbox.exec_shell(arguments.script)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.exit_code


def _prune(force_all: bool) -> int:
    from agentnest.reaper import prune

    try:
        report = prune(force_all=force_all)
    except Exception as exc:
        # Docker transport failures are not AgentNest types; report them plainly.
        print(f"prune failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "removed": report.total,
                "containers": report.containers,
                "networks": report.networks,
            },
            indent=2,
        )
    )
    return 0


def _demo() -> int:
    from agentnest import MemoryObserver

    observer = MemoryObserver()
    try:
        with Sandbox("python:3.12-slim", timeout=60, observers=(observer,)) as sandbox:
            print("Started a locked-down sandbox: non-root, read-only root, no network.")
            sandbox.write_file("demo.py", "print('hello from an isolated sandbox')")
            printed = sandbox.exec_shell("python demo.py")
            print(f"  ran a file       -> {printed.stdout.strip()}")

            session = sandbox.python_session()
            session.run("total = 0")
            for value in range(1, 5):
                session.run(f"total += {value}")
            print(f"  stateful session -> total is {session.run('total').check().result}")

            blocked = sandbox.exec_python(
                "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)"
            )
            print(f"  network egress   -> blocked by default: {not blocked.ok}")
        print(f"Sandbox destroyed. Captured {len(observer.events)} audit events.")
    except Exception as exc:
        # Surface a friendly hint for any setup issue (usually a missing daemon).
        print(f"demo could not run: {exc}", file=sys.stderr)
        print("Check your Docker setup with: agentnest doctor", file=sys.stderr)
        return 1
    return 0


def _doctor() -> int:
    report: dict[str, Any] = {"backends": registry.names(), "docker": False}
    try:
        import docker

        client = docker.from_env(timeout=3)
        report["docker"] = client.ping()
        report["docker_version"] = client.version().get("Version")
    except Exception as exc:
        report["docker_error"] = str(exc)
    print(json.dumps(report, indent=2))
    return 0 if report["docker"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
