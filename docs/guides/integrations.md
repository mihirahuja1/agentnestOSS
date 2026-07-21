# Framework integrations

AgentNest plugs into agent frameworks as a sandboxed code tool. Every adapter
wraps the same [`SandboxRunner`](https://github.com/mihirahuja1/agentnestOSS/blob/main/agentnest/integrations/base.py),
so the isolation, egress policy, and audit events are identical no matter which
framework calls it.

## Framework-neutral runner

```python
from agentnest.integrations import SandboxRunner

with SandboxRunner(network_enabled=False) as runner:
    print(runner.run("x = 21; print(x * 2)"))   # state persists across run() calls
```

## LangChain

```python
from agentnest.integrations.langchain import build_langchain_tool

tool = build_langchain_tool(network_enabled=False)   # a StructuredTool
# model.bind_tools([tool])  /  AgentExecutor(tools=[tool], ...)
```

Requires `pip install langchain-core`.

## smolagents

```python
from agentnest.integrations.smolagents import SandboxExecutor

executor = SandboxExecutor(network_enabled=False)
# Pass `executor` to a smolagents CodeAgent so its code actions run sandboxed.
```

Requires `pip install smolagents`. See the runnable
[`examples/`](https://github.com/mihirahuja1/agentnestOSS/tree/main/examples) for
end-to-end scripts.

## Model Context Protocol (MCP)

The MCP server exposes sandbox lifecycle and execution as tools any MCP client
(Claude Code, Cursor, Claude Desktop) can call:

```bash
pip install 'agentnest[mcp]'
agentnest mcp
```

Register it with a client — for example in a Claude Code / Cursor MCP config:

```json
{
  "mcpServers": {
    "agentnest": { "command": "agentnest", "args": ["mcp"] }
  }
}
```

The client then has `create_sandbox`, `exec_python`, `exec_shell`, `write_file`,
`read_file`, and `destroy_sandbox` tools — giving your assistant a safe place to
run code in one line of config.
