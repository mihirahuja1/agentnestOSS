# Policies and secrets

## Network access

```python
from agentnest import NetworkPolicy, SecurityPolicy

policy = SecurityPolicy(
    network=NetworkPolicy.allowlist(cidrs=("198.51.100.0/24",)),
    max_output_bytes=2_000_000,
    require_image_digest=True,
)
```

The Docker backend supports full deny or allow. It rejects fine-grained allowlists because Docker
cannot enforce them by itself. Kubernetes supports CIDR egress rules and rejects domain rules. Use a
policy-aware network proxy plugin for DNS allowlists.

## Image trust and host hardening

`allowed_images` constrains exact image references. `require_image_digest=True` prevents mutable tag
use. `seccomp_profile`, `apparmor_profile`, and `rootless=True` request host-backed controls. If the
daemon is not rootless when rootless is required, creation fails.

## Secrets

```python
from agentnest import Sandbox, Secret

with Sandbox(environment={"API_TOKEN": Secret("value")}) as sandbox:
    result = sandbox.exec_shell("python worker.py")
```

Only values explicitly wrapped in `Secret` are redacted. They become `[REDACTED]` in captured stdout
and stderr. Do not print secrets intentionally, persist them to workspace files, or assume redaction
protects transformed values.

## Approval hooks

Implement `approve(ApprovalRequest) -> bool` to gate execution, file operations, snapshots, and
restore. Hooks run before the backend operation. Denial raises `PolicyDeniedError`.

!!! note
    Policies are local controls, not user authorization. Authenticate and authorize API callers
    separately, and use cluster or host policy as another layer.
