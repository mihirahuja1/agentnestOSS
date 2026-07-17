# Architecture

AgentNest separates the developer API from the isolation mechanism. The high-level package knows
about sandbox lifecycle, execution results, files, and deadlines; it does not know about Docker
containers. This boundary is the main extensibility mechanism.

## Components

```mermaid
flowchart TB
    subgraph Public["Public package"]
        Sandbox["sandbox.py — lifecycle facade"]
        Results["models.py — config, limits, results"]
        Errors["exceptions.py — stable error hierarchy"]
    end

    subgraph Runtime["Runtime layer"]
        Base["runtime/base.py — abstract contract"]
        Docker["runtime/docker.py — Docker adapter"]
    end

    subgraph Support["Backend support"]
        Files["filesystem.py — path-safe file I/O"]
        Deadline["execution.py — bounded blocking calls"]
    end

    Sandbox --> Base
    Sandbox --> Results
    Base --> Docker
    Docker --> Files
    Docker --> Deadline
    Docker --> Daemon["Docker Engine"]
    Daemon --> Isolate["Non-root container"]
    Daemon --> Mount["Ephemeral /workspace bind mount"]
```

`Sandbox` accepts either a backend name or a `RuntimeBackend` instance. Dependency injection keeps
unit tests daemon-free and lets downstream applications prototype custom backends without forking
the public API.

## Lifecycle

```mermaid
sequenceDiagram
    participant App
    participant Sandbox
    participant Backend as RuntimeBackend
    participant Isolation as Container or future VM

    App->>Sandbox: Sandbox(config)
    Sandbox->>Backend: create(SandboxConfig)
    Backend->>Isolation: provision and start
    App->>Sandbox: exec_python / exec_shell
    Sandbox->>Backend: exec(command, deadline)
    Backend->>Isolation: execute as non-root
    Isolation-->>Backend: exit code, stdout, stderr
    Backend-->>App: ExecutionResult
    App->>Sandbox: destroy()
    Sandbox->>Backend: destroy()
    Backend->>Isolation: force remove
```

The total-lifetime timer starts only after successful creation. Each execution is capped by the
smaller of its requested timeout and the remaining sandbox lifetime. If the blocking backend call
exceeds that deadline, AgentNest removes the whole environment before raising
`ExecutionTimeoutError`. Destruction is idempotent.

## Docker backend

Each `DockerRuntime` owns exactly one container and one host temporary directory. The directory is
the only host path mounted into the container, at `/workspace`. The root filesystem is read-only by
default; restricted tmpfs mounts provide ephemeral scratch space. Captured `exec` output is retained
by the backend because Docker does not include exec output in the container log stream.

The fixed UID avoids image-specific root users. It also means images must provide a POSIX shell and,
for `exec_python`, a `python` executable. `python:*` images satisfy both requirements. Custom runtime
images should follow the same contract.

## Adding a backend

Implement all methods on `RuntimeBackend`:

1. `create` translates `SandboxConfig` into an isolated environment.
2. `exec` returns an `ExecutionResult` and enforces its supplied timeout.
3. `write_file` and `read_file` address relative workspace paths.
4. `logs` returns accumulated process output.
5. `destroy` is safe to call repeatedly and removes every owned resource.

Then register a short backend name in `Sandbox._resolve_backend`. No other public API changes are
required. A backend should map infrastructure failures into AgentNest exceptions and must document
any security guarantees weaker than the Docker defaults.

## Roadmap

The interfaces anticipate, but v1 does not implement:

- Kubernetes and remote execution backends
- gVisor, Kata Containers, and Firecracker isolation
- browser and GPU sandboxes
- MCP tool adapters
- snapshots, restore, and persistent workspaces
- parallel warm sandbox pools

Features should be added only when they fit the backend contract or justify a small,
backend-independent capability interface. AgentNest will not become a cluster orchestrator.

