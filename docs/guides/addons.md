# Add-on capabilities

AgentNest 0.2 groups advanced features around stable, optional interfaces.

| Capability | Primary API | Purpose |
| --- | --- | --- |
| Async | `AsyncSandbox.create()` | Keep event loops responsive |
| Streaming | `stream_shell()` | Incremental stdout/stderr and final status |
| Policies | `SecurityPolicy` | Network, images, output, rootless, LSM profiles |
| Approvals | `ApprovalHook` | Pause or deny sensitive operations |
| Audit events | `EventObserver` | Structured lifecycle and execution records |
| Secrets | `Secret` | Explicit redaction from captured process output |
| Templates | `Template` | Reproducible, cached runtime images |
| Snapshots | `snapshot()` / `restore()` | Checkpoint or fork workspace state |
| Pools | `SandboxPool` | Reuse warm capacity safely |
| Artifacts | `artifacts()` | Find and checksum outputs |
| Git | `GitWorkspace` | Clone, diff, status, and patch in isolation |
| Browser/GPU | presets | Curated resource defaults |
| MCP | `agentnest mcp` | Agent tool server |
| Remote API | `agentnest serve` | Dedicated execution hosts |

The APIs compose. A production coding agent can combine a pinned template, secret values, approval
hooks, JSON audit events, a gVisor backend, workspace snapshots, and a warm pool without changing how
commands or files are handled.
