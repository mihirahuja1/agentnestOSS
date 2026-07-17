# Kubernetes and remote workers

## Kubernetes

```bash
pip install 'agentnest[kubernetes]'
```

```python
from agentnest import Sandbox

with Sandbox(backend="kubernetes", memory="1Gi", cpus=1.0) as sandbox:
    sandbox.exec_python("print('inside a Pod')")
```

The backend creates an ephemeral Pod with no service-account token, a non-root security context,
dropped capabilities, read-only root, resource limits, memory-backed `/tmp`, an ephemeral workspace,
and deny-by-default ingress/egress NetworkPolicy.

Use a dedicated namespace with quotas and Pod Security Admission. For stronger isolation, instantiate
`KubernetesRuntime(runtime_class_name="gvisor")` or your configured Kata RuntimeClass.

## Remote execution API

On a dedicated execution host:

```bash
pip install 'agentnest[server]'
export AGENTNEST_API_TOKEN="replace-me"
agentnest serve --host 0.0.0.0 --port 8765
```

```python
from agentnest import Sandbox
from agentnest.runtime.remote import RemoteRuntime

backend = RemoteRuntime("https://runner.example.com", token="replace-me")
with Sandbox(backend=backend) as sandbox:
    sandbox.exec_python("print('remote')")
```

Terminate TLS at a trusted proxy, rotate tokens, restrict source networks, and use a dedicated node.
The API is versioned under `/v1`.

## Firecracker

`FirecrackerRuntime` uses the same remote protocol. The microVM lifecycle service belongs on a
Linux/KVM host and remains out of process, avoiding privileged KVM and network access in the SDK.
