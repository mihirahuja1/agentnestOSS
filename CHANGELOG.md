# Changelog

All notable changes are documented here. AgentNest follows Semantic Versioning after the `0.x`
development series.

## 0.3.0

### Added

- **Egress allowlisting** for the Docker backend: an internal network plus a
  filtering CONNECT-proxy sidecar enforce domain allowlists, so code can reach
  approved domains (e.g. PyPI) and provably nothing else
- **Stateful Python sessions** (`Sandbox.python_session`) backed by a persistent
  in-sandbox interpreter that keeps variables and imports across calls
- **Forkable sandboxes** (`Sandbox.fork`) that branch a running sandbox's state
  into an independent copy for speculative or parallel work
- **Crash-safe lifecycle**: every managed resource carries a deadline label, and
  `agentnest prune` reaps containers, proxies, and networks left by dead processes
- Framework integrations: `SandboxRunner`, a LangChain tool adapter, and a
  smolagents executor; expanded MCP guidance
- `agentnest demo` and `agentnest run "<code>"` for a zero-setup first run
- An adversarial escape-attempt test suite (`tests/escapes`) run in CI, and a
  reproducible benchmark script (`benchmarks/bench.py`)

### Changed

- Per-command timeouts now terminate only the offending process (via in-container
  `timeout`) and leave the sandbox alive and reusable; a host-side backstop still
  destroys sandboxes on images without coreutils `timeout`
- The Docker backend now enforces domain allowlists instead of rejecting them;
  raw CIDR allowlists still fail closed

### Fixed

- `read_file` no longer blocks forever on a FIFO planted in the workspace; it
  opens non-blocking and rejects non-regular files

## 0.2.0

### Added

- async execution and incremental Docker output streaming
- security and network policies, rootless checks, image trust controls, and output limits
- explicit secret redaction, approval hooks, and structured audit events
- deterministic templates, workspace snapshots, warm pools, and artifact discovery
- runtime plugin registry, gVisor/Kata selectors, Kubernetes backend, remote API, and Firecracker transport
- browser and GPU presets, Git helpers, MCP server, YAML profiles, and CLI
- Material for MkDocs documentation site, CI, security policy, and contributor guide

## 0.1.0

- initial Docker runtime, sandbox API, safe files, resource limits, tests, and documentation
