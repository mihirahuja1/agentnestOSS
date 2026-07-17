"""Git-oriented workspace helpers for coding agents."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from agentnest.models import ExecutionResult
from agentnest.sandbox import Sandbox


@dataclass(slots=True)
class GitWorkspace:
    """Operate on a repository entirely inside a sandbox workspace."""

    sandbox: Sandbox
    directory: str = "/workspace/repo"

    def clone(self, url: str, *, ref: str | None = None, depth: int = 1) -> ExecutionResult:
        if depth <= 0:
            raise ValueError("depth must be positive")
        command = ["git", "clone", "--depth", str(depth)]
        if ref:
            command.extend(["--branch", ref])
        command.extend([url, self.directory])
        return self.sandbox.exec_shell(" ".join(shlex.quote(part) for part in command))

    def diff(self, *, staged: bool = False) -> str:
        flag = " --cached" if staged else ""
        result = self.sandbox.exec_shell(
            f"git diff{flag} --no-ext-diff --", workdir=self.directory
        ).check()
        return result.stdout

    def status(self) -> str:
        return self.sandbox.exec_shell("git status --short", workdir=self.directory).check().stdout

    def apply_patch(self, patch: str) -> ExecutionResult:
        self.sandbox.write_file("repo/.agentnest.patch", patch)
        return self.sandbox.exec_shell(
            "git apply --whitespace=nowarn .agentnest.patch && rm .agentnest.patch",
            workdir=self.directory,
        )
