"""Run a smolagents CodeAgent's code inside an AgentNest sandbox.

Run:  pip install smolagents, then this file. The executor isolates every code
action the agent takes; nothing runs on the host.
"""

from __future__ import annotations

from agentnest.integrations.smolagents import SandboxExecutor


def main() -> None:
    executor = SandboxExecutor(network_enabled=False)
    try:
        # smolagents would call the executor with the code it generates. We
        # simulate two dependent actions to show state persisting between them.
        executor.send_variables({"threshold": 10})
        sieve = "primes = [n for n in range(2, 20) if all(n % d for d in range(2, n))]"
        first_output, _, _ = executor(sieve)
        second_output, _, is_final = executor("print([p for p in primes if p > threshold])")
        print("first action output:", first_output or "(no output)")
        print("second action output:", second_output)
        print("final answer?", is_final)
    finally:
        executor.cleanup()


if __name__ == "__main__":
    main()
