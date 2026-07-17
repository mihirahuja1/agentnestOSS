# Runtime backends

The public `Sandbox` API targets `RuntimeBackend`, not Docker. Backend instances own exactly one
sandbox lifecycle.

| Backend | Select with | Isolation | Status |
| --- | --- | --- | --- |
| Docker | `backend="docker"` | container | built in |
| gVisor | `backend="gvisor"` | Docker + `runsc` | built in; host runtime required |
| Kata | `backend="kata"` | Docker + Kata runtime | built in; host runtime required |
| Kubernetes | `backend="kubernetes"` | Pod / configured RuntimeClass | optional |
| Remote | `RemoteRuntime(url)` | server-defined | optional |
| Firecracker | `FirecrackerRuntime(url)` | remote microVM worker | optional transport |

## Third-party plugins

Publish a factory through the `agentnest.backends` entry-point group:

```toml
[project.entry-points."agentnest.backends"]
my-runtime = "my_package:create_backend"
```

Plugins must enforce deadlines, make destruction idempotent, fail closed for unsupported policies,
and avoid infrastructure-specific objects in public results.

Snapshot and streaming support use runtime-checkable capability protocols. A backend that does not
implement one receives `UnsupportedCapabilityError`; AgentNest never emulates a guarantee it cannot
safely provide.
