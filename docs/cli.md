# CLI

## Run code

```bash
agentnest run script.py --image python:3.12-slim --timeout 60
agentnest shell 'python -V' --memory 256m --cpus 0.5
```

The command exits with the sandboxed process status and preserves stdout/stderr channels.

## Inspect the environment

```bash
agentnest doctor
agentnest backends
agentnest --version
```

`doctor` prints machine-readable JSON and returns non-zero when Docker is unavailable.

## Start services

```bash
AGENTNEST_API_TOKEN=secret agentnest serve --host 127.0.0.1 --port 8765
agentnest mcp
```

Service commands provide an installation hint when their optional extra is missing.
