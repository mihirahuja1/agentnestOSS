"""In-sandbox persistent Python interpreter.

This runs as a background process inside a sandbox and keeps a single module
namespace alive across many evaluations, so variables, imports, and open handles
persist between calls -- the "code interpreter" model agents rely on for
iterative work. It talks to the host purely through files in a workspace
directory that is bind-mounted from the host, avoiding any need for extra ports
or sockets: the host drops ``req-<n>.py`` files and reads ``resp-<n>.json``
replies. It is stdlib-only and imported in-process by the test suite, so keep it
dependency-free.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import time
import traceback
from typing import Any

POLL_INTERVAL = 0.02


def execute(code: str, namespace: dict[str, Any]) -> dict[str, Any]:
    """Execute one snippet in ``namespace`` and capture its effects.

    The trailing expression, if any, is evaluated after the rest of the block so
    a bare ``df.head()`` returns a value the way an interactive prompt would.
    """

    out, err = io.StringIO(), io.StringIO()
    result: str | None = None
    error: str | None = None
    try:
        tree = ast.parse(code, "<session>", "exec")
    except SyntaxError:
        return {"stdout": "", "stderr": "", "error": traceback.format_exc(), "result": None}

    last_expression: ast.Expression | None = None
    last_statement = tree.body[-1] if tree.body else None
    if isinstance(last_statement, ast.Expr):
        tree.body.pop()
        last_expression = ast.Expression(last_statement.value)
        ast.copy_location(last_expression, last_statement.value)

    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            if tree.body:
                exec(compile(tree, "<session>", "exec"), namespace)
            if last_expression is not None:
                value = eval(compile(last_expression, "<session>", "eval"), namespace)
                if value is not None:
                    result = repr(value)
        except BaseException:
            # Any failure, including SystemExit, is reported back to the host.
            error = traceback.format_exc()
    return {
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "error": error,
        "result": result,
    }


def serve(root: str) -> None:
    namespace: dict[str, Any] = {"__name__": "__agentnest_session__"}
    os.makedirs(root, exist_ok=True)
    index = 0
    while True:
        request = os.path.join(root, f"req-{index}.py")
        if not os.path.exists(request):
            time.sleep(POLL_INTERVAL)
            continue
        with open(request, encoding="utf-8") as handle:
            code = handle.read()
        response = execute(code, namespace)
        temporary = os.path.join(root, f"resp-{index}.tmp")
        final = os.path.join(root, f"resp-{index}.json")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(response, handle)
        os.replace(temporary, final)
        os.remove(request)
        index += 1


if __name__ == "__main__":
    serve(os.environ.get("AGENTNEST_REPL_DIR", "/workspace/.agentnest-repl"))
