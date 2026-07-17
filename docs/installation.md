# Installation

## Core

```bash
pip install agentnest
```

The core depends only on the Docker SDK and Python's standard library.

## Optional capabilities

=== "Kubernetes"
    ```bash
    pip install 'agentnest[kubernetes]'
    ```
=== "Remote API"
    ```bash
    pip install 'agentnest[server]'
    ```
=== "MCP"
    ```bash
    pip install 'agentnest[mcp]'
    ```
=== "YAML profiles"
    ```bash
    pip install 'agentnest[profiles]'
    ```
=== "Everything"
    ```bash
    pip install 'agentnest[all]'
    ```

## Supported environments

AgentNest supports CPython 3.10–3.12. Docker Engine and Docker Desktop are supported for local
execution. Kubernetes requires credentials through in-cluster configuration or the active
`kubeconfig` context.

Run diagnostics after installation:

```bash
agentnest doctor
agentnest backends
```
