# Contributing to AgentNest

Thank you for improving secure agent execution. Start with the
[development guide](docs/development.md) and [architecture](docs/architecture.md).

## Before opening a pull request

1. Open an issue for changes that alter the public API or security model.
2. Keep infrastructure details behind `RuntimeBackend` or an optional capability protocol.
3. Add daemon-free unit tests and focused integration tests for runtime behavior.
4. Document guarantees, failure behavior, and backend limitations.
5. Run the complete local check set from the README.

Security fixes should be reported privately as described in [SECURITY.md](SECURITY.md).

By contributing, you agree that your contribution is licensed under Apache-2.0.
