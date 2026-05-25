"""Tests for the PF FHIR Patient search client.

HTTP is mocked with `responses`; see fixtures/ for recorded Bundle shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from lookup_patient.fhir_client import FhirClientError, read_patient, search_patient

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://qa-api.practicefusion.com/fhir/r4/v1/test-practice"
TOKEN = "test-access-token"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@responses.activate
def test_single_match_first_format():
    # First probe — PF default storage format — returns the patient.
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_single.json"),
        status=200,
        match=[
            responses.matchers.query_param_matcher(
                {"telecom": "(716) 361-9276", "birthdate": "1991-06-09"}
            )
        ],
    )
    result = search_patient("7163619276", "1991-06-09", BASE, TOKEN)

    assert result["match"] == "single"
    assert result["patient_id"] == "b79082d9-548c-454e-9fc7-ce19ab630776"
    assert result["winning_format"] == "(716) 361-9276"
    assert result["probes_tried"] == ["(716) 361-9276"]
    # Only ONE HTTP call — we stop probing on first match.
    assert len(responses.calls) == 1


@responses.activate
def test_falls_through_to_later_format():
    # First two formats miss; third (dashed) hits.
    responses.add(
        responses.GET, f"{BASE}/Patient",
        json=_load("bundle_empty.json"), status=200,
        match=[responses.matchers.query_param_matcher({"telecom": "(716) 361-9276", "birthdate": "1991-06-09"})],
    )
    responses.add(
        responses.GET, f"{BASE}/Patient",
        json=_load("bundle_empty.json"), status=200,
        match=[responses.matchers.query_param_matcher({"telecom": "+1(716)361-9276", "birthdate": "1991-06-09"})],
    )
    responses.add(
        responses.GET, f"{BASE}/Patient",
        json=_load("bundle_single.json"), status=200,
        match=[responses.matchers.query_param_matcher({"telecom": "716-361-9276", "birthdate": "1991-06-09"})],
    )
    result = search_patient("7163619276", "1991-06-09", BASE, TOKEN)

    assert result["match"] == "single"
    assert result["winning_format"] == "716-361-9276"
    assert result["probes_tried"] == ["(716) 361-9276", "+1(716)361-9276", "716-361-9276"]


@responses.activate
def test_no_match_all_formats_exhausted():
    # Every probe returns empty. Eight probes total per ADR-0006 priority list.
    for _ in range(8):
        responses.add(
            responses.GET,
            f"{BASE}/Patient",
            json=_load("bundle_empty.json"),
            status=200,
        )

    result = search_patient("7163619276", "1991-06-09", BASE, TOKEN)

    assert result["match"] == "none"
    assert result["patient_id"] is None
    assert result["winning_format"] is None
    assert len(result["probes_tried"]) == 8
    assert len(responses.calls) == 8


@responses.activate
def test_multiple_matches_returned_as_candidates():
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_multiple.json"),
        status=200,
    )

    result = search_patient("7163619276", "1991-06-09", BASE, TOKEN)

    assert result["match"] == "multiple"
    assert result["patient_id"] is None
    assert set(result["candidates"]) == {"patient-a", "patient-b"}
    assert result["winning_format"] == "(716) 361-9276"


@responses.activate
def test_sends_bearer_token():
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_single.json"),
        status=200,
    )
    search_patient("7163619276", "1991-06-09", BASE, TOKEN)
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


@responses.activate
def test_401_raises_client_error():
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json={"resourceType": "OperationOutcome"},
        status=401,
    )
    with pytest.raises(FhirClientError) as exc_info:
        search_patient("7163619276", "1991-06-09", BASE, TOKEN)
    assert "401" in str(exc_info.value)


@responses.activate
def test_500_raises_client_error():
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json={"resourceType": "OperationOutcome"},
        status=500,
    )
    with pytest.raises(FhirClientError):
        search_patient("7163619276", "1991-06-09", BASE, TOKEN)


def test_rejects_invalid_phone():
    with pytest.raises(FhirClientError):
        search_patient("abc", "1991-06-09", BASE, TOKEN)


@pytest.mark.parametrize("bad_dob", ["", "06-09-1991", "1991/06/09", "1991-6-9"])
def test_rejects_invalid_dob(bad_dob):
    with pytest.raises(FhirClientError):
        search_patient("7163619276", bad_dob, BASE, TOKEN)


# ---------------------------------------------------------------------------
# Name-based fallback (Session 0013)
# ---------------------------------------------------------------------------


@responses.activate
def test_name_fallback_when_phone_probes_exhausted():
    """When all 8 phone probes return empty and name is provided,
    search_patient should try family+given+birthdate as a fallback."""
    for _ in range(8):
        responses.add(
            responses.GET,
            f"{BASE}/Patient",
            json={"resourceType": "Bundle", "type": "searchset", "total": 0},
            status=200,
        )
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json={
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 1,
            "entry": [{"resource": {"resourceType": "Patient", "id": "nishant-001"}}],
        },
        status=200,
        match=[
            responses.matchers.query_param_matcher(
                {"family": "Salvi", "given": "Nishant", "birthdate": "1993-07-28"}
            )
        ],
    )
    result = search_patient(
        "7163619276",
        "1993-07-28",
        BASE,
        TOKEN,
        name_first="Nishant",
        name_last="Salvi",
    )
    assert result["match"] == "single"
    assert result["patient_id"] == "nishant-001"
    assert result["winning_format"] == "name+dob"
    assert len(responses.calls) == 9


@responses.activate
def test_name_fallback_not_tried_when_phone_matches():
    """When phone probe finds a match, name fallback is not attempted."""
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json={
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 1,
            "entry": [{"resource": {"resourceType": "Patient", "id": "mohit-001"}}],
        },
        status=200,
    )
    result = search_patient(
        "7163619276",
        "1991-06-09",
        BASE,
        TOKEN,
        name_first="Mohit",
        name_last="Durve",
    )
    assert result["match"] == "single"
    assert result["winning_format"] == "(716) 361-9276"
    assert len(responses.calls) == 1


@responses.activate
def test_name_fallback_not_tried_without_name():
    """Without name_first/name_last, phone-only exhaustion returns none."""
    for _ in range(8):
        responses.add(
            responses.GET,
            f"{BASE}/Patient",
            json={"resourceType": "Bundle", "type": "searchset", "total": 0},
            status=200,
        )
    result = search_patient("7163619276", "1993-07-28", BASE, TOKEN)
    assert result["match"] == "none"
    assert len(responses.calls) == 8


# ---------------------------------------------------------------------------
# Phone-only search (Session 0013 — proactive caller identification)
# ---------------------------------------------------------------------------


@responses.activate
def test_phone_only_search_finds_single_match():
    """Phone-only search (no DOB) returns a single patient."""
    from lookup_patient.fhir_client import search_patient_by_phone

    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_single.json"),
        status=200,
        match=[
            responses.matchers.query_param_matcher({"telecom": "(716) 361-9276"})
        ],
    )
    result = search_patient_by_phone("7163619276", BASE, TOKEN)
    assert result["match"] == "single"
    assert result["patient_id"] == "b79082d9-548c-454e-9fc7-ce19ab630776"


@responses.activate
def test_phone_only_search_returns_none():
    from lookup_patient.fhir_client import search_patient_by_phone

    for _ in range(6):
        responses.add(
            responses.GET,
            f"{BASE}/Patient",
            json=_load("bundle_empty.json"),
            status=200,
        )
    result = search_patient_by_phone("7163619276", BASE, TOKEN)
    assert result["match"] == "none"


@responses.activate
def test_phone_only_search_returns_multiple():
    from lookup_patient.fhir_client import search_patient_by_phone

    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_multiple.json"),
        status=200,
    )
    result = search_patient_by_phone("7163619276", BASE, TOKEN)
    assert result["match"] == "multiple"
    assert len(result["candidates"]) == 2


@responses.activate
def test_phone_only_search_refreshes_on_401():
    from lookup_patient.fhir_client import search_patient_by_phone

    responses.add(responses.GET, f"{BASE}/Patient", status=401, json={})
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_single.json"),
        status=200,
    )

    refreshed = []
    def _refresh():
        refreshed.append(True)
        return "new-token"

    result = search_patient_by_phone("7163619276", BASE, TOKEN, refresh_access_token=_refresh)
    assert result["match"] == "single"
    assert len(refreshed) == 1


@responses.activate
def test_read_patient_projects_enrichment_fields():
    responses.add(
        responses.GET,
        f"{BASE}/Patient/p-1",
        json={
            "resourceType": "Patient",
            "id": "p-1",
            "name": [{"family": "Doe", "given": ["Jane", "A."]}],
            "telecom": [{"system": "phone", "value": "+1 (415) 555-0199"}],
            "birthDate": "1980-12-31",
        },
        status=200,
    )
    out = read_patient("p-1", BASE, TOKEN)
    assert out == {
        "name_first": "Jane",
        "name_last": "Doe",
        "date_of_birth": "1980-12-31",
        "phone_masked": "0199",
    }


@responses.activate
def test_read_patient_refreshes_once_on_401():
    responses.add(responses.GET, f"{BASE}/Patient/p-2", status=401, json={})
    responses.add(
        responses.GET,
        f"{BASE}/Patient/p-2",
        json={
            "resourceType": "Patient",
            "id": "p-2",
            "name": [{"family": "Roe", "given": ["John"]}],
            "telecom": [{"system": "phone", "value": "5550000"}],
            "birthDate": "1970-01-01",
        },
        status=200,
    )
    refreshed = []

    def _refresh() -> str:
        refreshed.append(True)
        return "new-token"

    out = read_patient("p-2", BASE, TOKEN, refresh_access_token=_refresh)
    assert out["name_first"] == "John"
    assert out["phone_masked"] == "0000"
    assert refreshed == [True]


@responses.activate
def test_read_patient_handles_missing_fields():
    responses.add(
        responses.GET,
        f"{BASE}/Patient/p-3",
        json={"resourceType": "Patient", "id": "p-3"},
        status=200,
    )
    out = read_patient("p-3", BASE, TOKEN)
    assert out == {
        "name_first": "",
        "name_last": "",
        "date_of_birth": "",
        "phone_masked": "",
    }
