"""Integration tests against live Practice Fusion QA — fhir_client direct.

Validates ADR-0006 (natural-language phone input → multi-format probe
loop → match). Bypasses the handler so the FHIR-search logic is tested
in isolation; the full vertical-slice flow lives in
``test_integration_handler.py``.

Session 0006 finding: PF invalidates prior access tokens when a new
refresh-grant exchange happens. Both this file and
``test_integration_handler.py`` need fresh access tokens; the
``pf_access_token`` session-scoped fixture in ``conftest.py`` mints
once per pytest session and serves it to every fhir-direct test below.
"""

from __future__ import annotations

import os

import pytest

from lookup_patient.fhir_client import search_patient

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "phone_input,expected_id",
    [
        # ADR-0006 validation: any common US format must resolve.
        ("716 361 9276", "b79082d9-548c-454e-9fc7-ce19ab630776"),
        ("7163619276", "b79082d9-548c-454e-9fc7-ce19ab630776"),
        ("+17163619276", "b79082d9-548c-454e-9fc7-ce19ab630776"),
        ("(716) 491-6872", "8c6bba93-8e6c-4dc4-b85a-c8edfe487786"),
        ("716-491-6872", "8c6bba93-8e6c-4dc4-b85a-c8edfe487786"),
    ],
)
def test_durve_patients_resolve_from_natural_input(
    phone_input, expected_id, pf_access_token
):
    result = search_patient(
        phone_input,
        "1991-06-09",
        os.environ["PF_FHIR_BASE_URL"],
        pf_access_token,
    )
    assert result["match"] == "single", result
    assert result["patient_id"] == expected_id
