"""Shared integration-test helpers.

Session 0006 finding: PF invalidates prior access tokens when a new
refresh-grant exchange happens. The existing fhir-direct tests
(``test_integration_pf.py``) and the new full-handler test
(``test_integration_handler.py``) both refresh against PF — running
them together would otherwise have the second to refresh invalidate
the first's access token mid-test.

This fixture mints **once per pytest session** via the live PF token
endpoint and serves the resulting access token to every integration
test that asks for it. The handler integration test does its own
refresh (intentionally — it's testing that path); the fhir-direct
tests share this one.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def pf_access_token() -> str:
    """Mint a fresh PF QA access token once per test session.

    Skips the test (not fails) when the refresh-token env vars aren't set;
    the unit-layer pytest run has them absent and we don't want noise.
    """
    required = ("PF_FHIR_BASE_URL", "PF_REFRESH_TOKEN", "PF_CLIENT_ID", "PF_CLIENT_SECRET")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        pytest.skip(f"integration: missing env vars: {missing}")

    from oauth.refresh import refresh_access_token
    from oauth.well_known import fetch_smart_configuration

    token_endpoint = fetch_smart_configuration(os.environ["PF_FHIR_BASE_URL"]).token_endpoint
    ts = refresh_access_token(
        refresh_token=os.environ["PF_REFRESH_TOKEN"],
        token_endpoint=token_endpoint,
        client_id=os.environ["PF_CLIENT_ID"],
        client_secret=os.environ["PF_CLIENT_SECRET"],
    )
    return ts.access_token
