"""Meta-test for `make test-ci`.

Asserts the Makefile recipe lists all four layer markers when run under
`make -n` (dry-run). This is the green-bar gate that every session from
0006 onward must respect.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ci import LAYER_MARKERS

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("make") is None, reason="make not on PATH")
def test_test_ci_invokes_all_four_layers() -> None:
    result = subprocess.run(
        ["make", "-n", "test-ci"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout
    for marker in LAYER_MARKERS:
        assert f"::ci-layer::{marker}" in output, (
            f"layer marker {marker!r} missing from `make -n test-ci` output:\n{output}"
        )
