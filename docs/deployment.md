# Deployment

## Choose the boundary

| Workload | Recommended boundary |
| --- | --- |
| Local development, trusted tools | Docker Desktop or rootless Docker |
| Single-tenant production agents | Dedicated Docker host with pinned images |
| Hostile code on shared nodes | gVisor or Kata |
| Cluster workloads | Kubernetes with RuntimeClass, quotas, and NetworkPolicy |
| Strong tenant boundary | Firecracker worker on dedicated Linux/KVM hosts |

## Production checklist

- Pin every runtime image by digest and scan it before use.
- Use dedicated execution nodes and never expose the Docker socket to sandbox code.
- Keep networking denied; otherwise enforce egress outside the container.
- Set resource, process, output, file, and lifetime limits conservatively.
- Use rootless Docker where supported and a current seccomp/AppArmor/SELinux policy.
- Authenticate the remote API, terminate TLS, rotate tokens, and restrict source networks.
- Export audit events and alert on timeouts, OOM exits, policy denials, and cleanup errors.
- Sweep stale resources labeled `agentnest.managed=true` after daemon or node failures.
- Treat snapshots, artifacts, templates, and logs as potentially hostile data.

## Docker Compose development

```bash
docker compose run --rm test
```

The development service mounts the Docker socket. This grants daemon-level host control and is only
appropriate on a trusted development machine.
