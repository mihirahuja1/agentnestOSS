"""Move binary files between the host and an isolated workspace."""

from pathlib import Path

from agentnest import Sandbox

source = Path("input.txt")
source.write_text("a temporary example\n", encoding="utf-8")

with Sandbox("python:3.12-slim", timeout=60) as sandbox:
    sandbox.upload_file(source, "input.txt")
    sandbox.exec_python(
        "from pathlib import Path; "
        "Path('output.txt').write_text(Path('input.txt').read_text().upper())"
    ).check()
    sandbox.download_file("output.txt", "output.txt")

print(Path("output.txt").read_text(encoding="utf-8"), end="")
