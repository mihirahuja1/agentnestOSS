"""Exception hierarchy for AgentNest."""


class AgentNestError(Exception):
    """Base class for all AgentNest errors."""


class RuntimeNotAvailableError(AgentNestError):
    """Raised when a requested runtime cannot be reached or created."""


class SandboxDestroyedError(AgentNestError):
    """Raised when an operation targets a destroyed sandbox."""


class ExecutionError(AgentNestError):
    """Raised when execution cannot be started or completed."""


class ExecutionTimeoutError(ExecutionError):
    """Raised when an execution exceeds its deadline.

    The sandbox is destroyed when this happens so timed-out code cannot continue
    running out of sight.
    """


class FileAccessError(AgentNestError):
    """Raised for unsafe, missing, or invalid workspace file operations."""
