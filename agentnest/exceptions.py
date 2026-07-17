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


class PolicyDeniedError(AgentNestError):
    """Raised when a security policy or approval hook rejects an action."""


class UnsupportedCapabilityError(AgentNestError):
    """Raised when a backend cannot safely provide a requested capability."""


class PoolExhaustedError(AgentNestError):
    """Raised when a sandbox pool cannot provide an instance before its deadline."""
