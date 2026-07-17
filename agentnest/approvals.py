"""Approval hooks for sensitive sandbox actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from agentnest.exceptions import PolicyDeniedError


class Action(str, Enum):
    EXECUTE = "execute"
    EXECUTE_PYTHON = "execute_python"
    EXECUTE_SHELL = "execute_shell"
    WRITE_FILE = "write_file"
    READ_FILE = "read_file"
    SNAPSHOT = "snapshot"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    action: Action
    sandbox_id: str
    details: dict[str, Any] = field(default_factory=dict)


class ApprovalHook(Protocol):
    def approve(self, request: ApprovalRequest) -> bool: ...


class AllowAll:
    def approve(self, request: ApprovalRequest) -> bool:
        return True


class DenyAll:
    def approve(self, request: ApprovalRequest) -> bool:
        return False


def require_approval(hook: ApprovalHook, request: ApprovalRequest) -> None:
    if not hook.approve(request):
        raise PolicyDeniedError(f"sandbox action was denied: {request.action.value}")
