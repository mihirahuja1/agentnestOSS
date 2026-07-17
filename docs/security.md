# Security

AgentNest uses Docker controls to reduce the privileges of executed code. It is secure by default in
the sense that dangerous capabilities are opt-in and resource boundaries are always configured. It
does not claim that ordinary containers are equivalent to micro-VMs for every adversary.

## Default controls

The Docker backend runs UID/GID 65532, disables privileged mode and networking, drops all Linux
capabilities, enables `no-new-privileges`, makes the root filesystem read-only, limits memory, CPU,
PIDs, and scratch tmpfs size, and mounts only a newly created workspace directory. The container and
workspace are deleted on explicit destruction, context exit, lifetime expiry, or command timeout.

File APIs reject absolute paths and `..` traversal. Directory-relative, no-follow file descriptors
prevent both symlink escapes and symlink-swap races. Reads have a 64 MiB defensive limit. The public
API intentionally has no arbitrary volume-mount option.

## Trust boundaries

- The AgentNest host process and Docker daemon are trusted.
- Runtime images are part of the trusted computing base. Pin production images by digest, minimize
  installed software, and scan them.
- The host kernel remains shared with containers. For strongly hostile multi-tenant workloads,
  use the gVisor, Kata, Kubernetes RuntimeClass, or Firecracker worker integrations.
- Enabling networking permits data exfiltration and access to whatever the Docker network can reach.
  Use egress policy outside AgentNest when finer control is needed.
- Resource limits mitigate denial of service; they do not eliminate daemon, disk, or kernel-level
  exhaustion risks. Apply host-level quotas and monitoring.

## Operational recommendations

Use a dedicated Docker daemon or node, keep the host and daemon patched, pin images, leave networking
off, set short timeouts, size limits conservatively, and monitor managed containers through the
`agentnest.managed=true` label. Do not expose the Docker socket to untrusted users or code.

Report suspected vulnerabilities privately to the project maintainers rather than opening a public
issue containing exploit details.

## Fail-closed policy behavior

Backends reject controls they cannot enforce. Docker rejects domain/CIDR allowlists. Kubernetes
rejects domain allowlists but can create CIDR NetworkPolicy rules. Rootless policy checks the daemon
before creating a container. Image allowlists and digest requirements are validated before pulling.
Captured output has a bounded size, and explicit `Secret` values are redacted.
