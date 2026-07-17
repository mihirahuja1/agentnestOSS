# Configuration profiles

```bash
pip install 'agentnest[profiles]'
```

```yaml title="agentnest.yaml"
default:
  runtime: python:3.12-slim
  timeout: 120
  memory: 512m
  cpus: 1.0
  network:
    mode: deny
```

```python
from agentnest import Sandbox
from agentnest.profiles import SandboxProfile

profile = SandboxProfile.load("agentnest.yaml", "default")
with Sandbox(**profile.options) as sandbox:
    ...
```

Profiles use `yaml.safe_load` and validate network policy objects. Treat profile files as trusted
deployment configuration; template commands and image references can execute code.
