# Python API

The package root exports the stable API. Infrastructure adapters live under `agentnest.runtime`.

## Sandbox

::: agentnest.Sandbox
    options:
      members: [exec, exec_python, exec_shell, stream_shell, exec_json, write_file, read_file, upload_file, download_file, artifacts, snapshot, restore, logs, destroy]

## AsyncSandbox

::: agentnest.AsyncSandbox

## Results and resources

::: agentnest.models.ExecutionResult
::: agentnest.models.ExecutionChunk
::: agentnest.models.ResourceLimits
::: agentnest.artifacts.Artifact

## Policies

::: agentnest.policy.SecurityPolicy
::: agentnest.policy.NetworkPolicy

## Templates and pools

::: agentnest.templates.Template
::: agentnest.pool.SandboxPool

## Runtime contract

::: agentnest.runtime.base.RuntimeBackend
