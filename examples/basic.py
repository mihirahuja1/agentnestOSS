"""Execute Python, shell, and file operations in one short-lived sandbox."""

from agentnest import Sandbox

with Sandbox("python:3.12-slim", timeout=60) as sandbox:
    sandbox.write_file("name.txt", "AgentNest")

    result = sandbox.exec_python(
        "from pathlib import Path; print(f'Hello, {Path(\"name.txt\").read_text()}!')"
    )
    result.check()
    print(result.stdout, end="")

    shell = sandbox.exec_shell("printf 'finished' > status.txt")
    shell.check()
    print(sandbox.read_file("status.txt"))
