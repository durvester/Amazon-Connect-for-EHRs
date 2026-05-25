"""Drive a synthetic Connect ContactEvent at the agent runtime (CI agent-e2e layer).

Session 0005 placeholder. Real Strands agent + Connect event playback
land in Session 0010; this module's job today is to assert that the
local-invoke shim can be imported and called without error, so the
harness slot is real.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--placeholder", action="store_true")
    args = parser.parse_args(argv)
    del args

    try:
        from agent.local_invoke import invoke_synthetic  # type: ignore
    except Exception as e:
        print(f"run_synthetic_call: cannot import agent.local_invoke: {e}", file=sys.stderr)
        return 2

    result = invoke_synthetic()
    if result != "ok":
        print(f"run_synthetic_call: shim returned {result!r}, expected 'ok'", file=sys.stderr)
        return 2
    print("# run_synthetic_call: shim invocation green (placeholder).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
