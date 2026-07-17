# Security policy

AgentNest executes potentially hostile code and treats vulnerability reports seriously.

Please do not open a public issue for suspected container escapes, host filesystem access, policy
bypasses, secret exposure, authentication bypasses, or cleanup failures. Contact the repository
owner privately through GitHub with a minimal reproduction, affected version, impact, and suggested
embargo timeline.

The current `0.x` series receives security fixes on the latest minor release. Ordinary Docker
containers are not represented as a universal multi-tenant security boundary; see the complete
[security model](docs/security.md).
