"""Enable networking explicitly for a workload that downloads a package."""

from agentnest import Sandbox

with Sandbox("python:3.12-slim", timeout=120, network_enabled=True) as sandbox:
    install = sandbox.exec_shell("pip install --disable-pip-version-check requests")
    install.check()

    result = sandbox.exec_python("import requests; print(requests.__version__)")
    result.check()
    print(result.stdout, end="")
