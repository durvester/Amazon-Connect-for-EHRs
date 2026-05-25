"""Start the local API stack and run UI-E2E specs (CI Layer 3).

Two modes:

  ``--healthz-only``  (Session 0005)
      Free port, ``api.app:build_app`` factory (healthz-only when env
      vars aren't wired), runs ``tests/e2e/healthz.spec.ts`` if
      Playwright is installed.

  ``--onboarding``    (Session 0008)
      Port 8080 (Veradigm-registered redirect URI for PF QA),
      ``ci.local_onboarding_app:build_app`` factory which starts moto
      in-process + wires the onboarding routes + stubs the Connect DID
      claim. Runs every spec in ``tests/e2e/`` (the OAuth spec inside
      will self-skip if ``PF_QA_USERNAME``/``PF_QA_PASSWORD`` aren't set).
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ONBOARDING_PORT = 8080  # Veradigm-registered redirect URI; do not change.


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_healthz(url: str, *, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except Exception as e:
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"healthz never came up at {url}: {last_err}")


def _run_playwright(base_url: str, *, spec: str | None = None) -> int:
    pw_pkg = REPO_ROOT / "web" / "node_modules" / "@playwright" / "test"
    if not pw_pkg.exists():
        print("# start_local_stack: Playwright not installed; python /healthz probe only.")
        return 0

    cmd = ["npx", "playwright", "test"]
    if spec:
        cmd.append(spec)
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT / "web",
        env={**os.environ, "PLAYWRIGHT_BASE_URL": base_url},
    )
    return proc.returncode


def _start_uvicorn(*, factory: str, cwd: Path, port: int) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "uvicorn",
        factory, "--factory",
        "--host", "127.0.0.1", "--port", str(port),
        "--log-level", "warning",
    ]
    return subprocess.Popen(cmd, cwd=cwd, env=os.environ.copy())


def _run_healthz_only() -> int:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = _start_uvicorn(
        factory="api.app:build_app",
        cwd=REPO_ROOT / "api",
        port=port,
    )
    try:
        _wait_for_healthz(f"{base_url}/healthz")
        print(f"# start_local_stack: /healthz green on {base_url}")
        spec = REPO_ROOT / "web" / "tests" / "e2e" / "healthz.spec.ts"
        if not spec.exists():
            return 0
        return _run_playwright(base_url, spec="tests/e2e/healthz.spec.ts")
    finally:
        _terminate(proc)


def _run_onboarding() -> int:
    """Boot the full onboarding stack on port 8080 + run all e2e specs."""
    base_url = f"http://127.0.0.1:{ONBOARDING_PORT}"
    pythonpath = os.pathsep.join(
        [
            str(REPO_ROOT / "ci" / "src"),
            str(REPO_ROOT / "api" / "src"),
            str(REPO_ROOT / "oauth" / "src"),
            str(REPO_ROOT / "routing" / "src"),
            os.environ.get("PYTHONPATH", ""),
        ]
    )
    os.environ["PYTHONPATH"] = pythonpath

    proc = _start_uvicorn(
        factory="ci.local_onboarding_app:build_app",
        cwd=REPO_ROOT,
        port=ONBOARDING_PORT,
    )
    try:
        _wait_for_healthz(f"{base_url}/healthz")
        print(f"# start_local_stack: onboarding stack green on {base_url}")
        # Run every spec — the OAuth spec self-skips if creds are absent.
        return _run_playwright(base_url)
    finally:
        _terminate(proc)


def _terminate(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--healthz-only", action="store_true")
    mode.add_argument(
        "--onboarding",
        action="store_true",
        help="Run the full onboarding stack on port 8080 + every e2e spec.",
    )
    args = parser.parse_args(argv)

    if args.onboarding:
        return _run_onboarding()
    return _run_healthz_only()


if __name__ == "__main__":
    raise SystemExit(main())
