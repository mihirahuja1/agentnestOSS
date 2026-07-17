"""Run the same public API against a configured Kubernetes cluster."""

from agentnest import Sandbox

with Sandbox(
    "python:3.12-slim",
    backend="kubernetes",
    timeout=120,
    memory="512Mi",
) as sandbox:
    result = sandbox.exec_python("import platform; print(platform.node())")
    result.check()
    print(result.stdout, end="")
