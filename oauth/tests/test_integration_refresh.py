"""Integration test: refresh against live PF QA and verify the minted access
token works for an unattended `Patient.read` (the ADR-0003 question).

Skipped unless these env vars are set:
    PF_FHIR_BASE_URL
    PF_REFRESH_TOKEN
    PF_CLIENT_ID
    PF_CLIENT_SECRET

Token endpoint is discovered from `{base}/.well-known/smart-configuration`,
matching the production refresh path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from oauth.refresh import refresh_access_token
from oauth.well_known import fetch_smart_configuration

# Reach the lookup_patient package without installing it: add its src/ to path.
_LOOKUP_SRC = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "lookup_patient"
    / "src"
)
if str(_LOOKUP_SRC) not in sys.path:
    sys.path.insert(0, str(_LOOKUP_SRC))

from lookup_patient.fhir_client import search_patient  # noqa: E402

pytestmark = pytest.mark.integration

_REQUIRED_ENV = (
    "PF_FHIR_BASE_URL",
    "PF_REFRESH_TOKEN",
    "PF_CLIENT_ID",
    "PF_CLIENT_SECRET",
)


def _need_env():
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        pytest.skip(f"integration: missing env vars: {missing}")


def test_refresh_mints_access_token_that_validates_adr0003():
    _need_env()
    smart = fetch_smart_configuration(os.environ["PF_FHIR_BASE_URL"])

    tokens = refresh_access_token(
        refresh_token=os.environ["PF_REFRESH_TOKEN"],
        token_endpoint=smart.token_endpoint,
        client_id=os.environ["PF_CLIENT_ID"],
        client_secret=os.environ["PF_CLIENT_SECRET"],
    )

    assert tokens.access_token, "PF returned no access_token"
    assert tokens.expires_in > 0
    # ADR-0003 validation: scope echo must still include user/Patient.read,
    # i.e., PF accepts our user-scope refresh and re-grants the scope set.
    assert "user/Patient.read" in tokens.scope

    # Now exercise the minted token against the same lookup the spike did.
    result = search_patient(
        "7163619276",
        "1991-06-09",
        os.environ["PF_FHIR_BASE_URL"],
        tokens.access_token,
    )
    assert result["match"] == "single", result
    assert result["patient_id"] == "b79082d9-548c-454e-9fc7-ce19ab630776"
