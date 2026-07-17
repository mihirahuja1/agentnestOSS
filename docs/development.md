# Development guide

## Prerequisites

- Python 3.10 or newer
- Docker Engine or Docker Desktop
- Git

Create an environment and install all developer dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

## Quality checks

Run the fast checks before opening a change:

```bash
ruff check .
ruff format --check .
mypy agentnest
pytest --cov=agentnest --cov-report=term-missing
```

Unit tests use an in-memory backend and do not require Docker. Integration tests are opt-in because
they pull images and create real containers:

```bash
AGENTNEST_DOCKER_TESTS=1 pytest -m integration -v
```

To run everything in a development container:

```bash
docker compose build test
docker compose run --rm test
```

The Compose setup mounts `/var/run/docker.sock`. Anyone controlling that socket effectively controls
the host. Do not use this setup with untrusted test code or on shared infrastructure.

## Repository layout

```text
agentnest/
  runtime/base.py       backend interface
  runtime/docker.py     Docker adapter
  sandbox.py            public lifecycle API
  filesystem.py         safe workspace paths and I/O
  execution.py          timeout enforcement
  models.py             immutable configuration and results
  exceptions.py         public errors
tests/                  unit and opt-in integration tests
examples/               runnable usage examples
docs/                   design, security, and contributor docs
```

## Change guidelines

- Keep infrastructure-specific types inside their backend module.
- Preserve secure defaults. A weaker mode must be explicit and documented.
- Add daemon-free unit coverage for public behavior and focused integration coverage for backend
  behavior.
- Never accept arbitrary host mount paths through the public API.
- Make cleanup idempotent, including partial-create and daemon-failure paths.
- Return captured failures as `ExecutionResult`; reserve exceptions for lifecycle, transport,
  timeout, and invalid-operation failures.

## Release process

1. Update the version in `pyproject.toml` and summarize user-visible changes.
2. Run all checks and Docker integration tests.
3. Build with `python -m build` and inspect wheel contents.
4. Tag the reviewed commit and publish through the project's trusted release workflow.

