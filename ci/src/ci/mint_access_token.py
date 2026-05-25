"""Mint a PF QA access token at the start of a CI run.

Two modes:
  --skip-if-no-fixture  Probe-only. Exit 0 with a printed warning if the
                        fixture or private key is unavailable. Used by the
                        unit layer so unit tests never block on QA creds.
  --export-env          Decrypt the fixture, refresh against PF QA, and
                        print KEY=VALUE lines suitable for `set -a; . file`.
                        Exits non-zero if anything fails.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urljoin

from ci._fixture import FixtureUnavailable, decrypt_bundle


def _discover_token_endpoint(fhir_base_url: str) -> str:
    import requests

    from oauth.well_known import fetch_smart_configuration  # type: ignore

    try:
        return fetch_smart_configuration(fhir_base_url).token_endpoint
    except Exception:
        # Fallback: PF's per-tenant convention. Discovery is preferred (see
        # Session 0004 finding) but should not block CI if .well-known is
        # transiently unavailable.
        del requests  # silence unused-import linter when fallback fires
        return urljoin(fhir_base_url.rstrip("/") + "/", "token")


def _refresh(bundle) -> dict[str, str]:
    from oauth.refresh import refresh_access_token  # type: ignore

    token_endpoint = _discover_token_endpoint(bundle.fhir_base_url)
    ts = refresh_access_token(
        refresh_token=bundle.refresh_token,
        token_endpoint=token_endpoint,
        client_id=bundle.client_id,
        client_secret=bundle.client_secret,
    )
    return {
        "PF_FHIR_BASE_URL": bundle.fhir_base_url,
        "PF_ACCESS_TOKEN": ts.access_token,
        "PF_REFRESH_TOKEN": ts.refresh_token,
        "PF_CLIENT_ID": bundle.client_id,
        "PF_CLIENT_SECRET": bundle.client_secret,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--skip-if-no-fixture", action="store_true")
    grp.add_argument("--export-env", action="store_true")
    args = parser.parse_args(argv)

    try:
        bundle = decrypt_bundle()
    except FixtureUnavailable as e:
        if args.skip_if_no_fixture:
            print(f"# mint_access_token: fixture unavailable ({e}); skipping.",
                  file=sys.stderr)
            return 0
        print(f"mint_access_token: {e}", file=sys.stderr)
        return 2

    env = _refresh(bundle)
    if args.export_env:
        for k, v in env.items():
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
