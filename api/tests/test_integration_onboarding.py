"""Real PF QA integration: code-exchange leg of /oauth/callback.

The full onboarding round-trip requires a human-in-the-browser
authorization grant to produce the SMART `code` — that's not
automatable in CI. This test exercises the *headless* portion of the
flow against real PF QA: given a fresh, one-time auth code + verifier
captured manually, swap it for tokens at the real token endpoint.

Skipped unless the PF_AUTH_CODE_* env vars are present. On the rare
session that captures a fresh code, run this once to prove the
exchange works end-to-end before tossing the consumed code.
"""

from __future__ import annotations

import os

import pytest

REQUIRED = (
    "PF_AUTH_CODE",
    "PF_AUTH_CODE_VERIFIER",
    "PF_TOKEN_ENDPOINT",
    "PF_CLIENT_ID",
    "PF_CLIENT_SECRET",
    "PF_REDIRECT_URI",
)


@pytest.mark.integration
def test_code_exchange_against_pf_qa() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip(f"integration: missing env vars: {missing}")

    from oauth.code_exchange import exchange_authorization_code

    out = exchange_authorization_code(
        code=os.environ["PF_AUTH_CODE"],
        code_verifier=os.environ["PF_AUTH_CODE_VERIFIER"],
        token_endpoint=os.environ["PF_TOKEN_ENDPOINT"],
        client_id=os.environ["PF_CLIENT_ID"],
        client_secret=os.environ["PF_CLIENT_SECRET"],
        redirect_uri=os.environ["PF_REDIRECT_URI"],
    )
    assert out.access_token
    assert out.refresh_token
    assert "user/Patient.read" in out.scope or out.scope == ""
