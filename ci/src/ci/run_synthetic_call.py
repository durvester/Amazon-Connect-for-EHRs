"""CI agent-e2e layer placeholder.

The agent/ package (Strands SDK stubs) was removed during cleanup.
Real agent-e2e tests will exercise lex_code_hook directly when ready.
"""

from __future__ import annotations

import argparse
import sys


def _invoke_placeholder() -> str:
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--placeholder", action="store_true")
    parser.parse_args(argv)

    result = _invoke_placeholder()
    if result != "ok":
        print(f"run_synthetic_call: shim returned {result!r}, expected 'ok'", file=sys.stderr)
        return 2
    print("# run_synthetic_call: placeholder green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
