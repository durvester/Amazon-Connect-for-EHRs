"""Tests for fhir_query FHIR client — generalized FHIR search."""

from __future__ import annotations

import pytest
import responses

from fhir_query.fhir_client import FhirQueryError, search_resources

BASE_URL = "https://api.practicefusion.com/fhir/r4/v1/test-org"
TOKEN = "test-access-token"


def _bundle(entries: list[dict], total: int | None = None) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": total if total is not None else len(entries),
        "entry": [{"resource": e} for e in entries],
    }


def _empty_bundle() -> dict:
    return {"resourceType": "Bundle", "type": "searchset", "total": 0}


class TestSearchResources:
    @responses.activate
    def test_returns_entries_from_bundle(self):
        dr = {"resourceType": "DiagnosticReport", "id": "dr-1", "status": "final"}
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json=_bundle([dr]),
            status=200,
        )
        result = search_resources(
            resource_type="DiagnosticReport",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert len(result) == 1
        assert result[0]["id"] == "dr-1"

    @responses.activate
    def test_returns_empty_list_for_no_results(self):
        responses.get(
            f"{BASE_URL}/MedicationRequest",
            json=_empty_bundle(),
            status=200,
        )
        result = search_resources(
            resource_type="MedicationRequest",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert result == []

    @responses.activate
    def test_passes_params_as_query_string(self):
        responses.get(
            f"{BASE_URL}/Observation",
            json=_empty_bundle(),
            status=200,
        )
        search_resources(
            resource_type="Observation",
            params={"patient": "p-123", "category": "laboratory", "_count": "5"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert "patient=p-123" in responses.calls[0].request.url
        assert "category=laboratory" in responses.calls[0].request.url
        assert "_count=5" in responses.calls[0].request.url

    @responses.activate
    def test_sends_bearer_token(self):
        responses.get(
            f"{BASE_URL}/Encounter",
            json=_empty_bundle(),
            status=200,
        )
        search_resources(
            resource_type="Encounter",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert responses.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"

    @responses.activate
    def test_raises_on_non_2xx(self):
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json={"issue": [{"severity": "error"}]},
            status=500,
        )
        with pytest.raises(FhirQueryError, match="500"):
            search_resources(
                resource_type="DiagnosticReport",
                params={"patient": "p-123"},
                base_url=BASE_URL,
                access_token=TOKEN,
            )


class TestTokenRefresh:
    @responses.activate
    def test_retries_once_on_401(self):
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json={"issue": [{"severity": "error", "code": "security"}]},
            status=401,
        )
        dr = {"resourceType": "DiagnosticReport", "id": "dr-1", "status": "final"}
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json=_bundle([dr]),
            status=200,
        )

        new_token = "refreshed-token"
        refresh_calls = []

        def mock_refresh() -> str:
            refresh_calls.append(1)
            return new_token

        result = search_resources(
            resource_type="DiagnosticReport",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
            refresh_access_token=mock_refresh,
        )
        assert len(result) == 1
        assert len(refresh_calls) == 1
        assert responses.calls[1].request.headers["Authorization"] == f"Bearer {new_token}"

    @responses.activate
    def test_raises_on_401_without_refresh(self):
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json={"issue": [{"severity": "error"}]},
            status=401,
        )
        with pytest.raises(FhirQueryError, match="401"):
            search_resources(
                resource_type="DiagnosticReport",
                params={"patient": "p-123"},
                base_url=BASE_URL,
                access_token=TOKEN,
            )

    @responses.activate
    def test_raises_on_401_after_refresh(self):
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json={"issue": [{"severity": "error"}]},
            status=401,
        )
        responses.get(
            f"{BASE_URL}/DiagnosticReport",
            json={"issue": [{"severity": "error"}]},
            status=401,
        )

        def mock_refresh() -> str:
            return "new-token"

        with pytest.raises(FhirQueryError, match="401"):
            search_resources(
                resource_type="DiagnosticReport",
                params={"patient": "p-123"},
                base_url=BASE_URL,
                access_token=TOKEN,
                refresh_access_token=mock_refresh,
            )


class TestMultipleEntries:
    @responses.activate
    def test_returns_multiple_resources(self):
        entries = [
            {"resourceType": "MedicationRequest", "id": f"med-{i}", "status": "active"}
            for i in range(5)
        ]
        responses.get(
            f"{BASE_URL}/MedicationRequest",
            json=_bundle(entries),
            status=200,
        )
        result = search_resources(
            resource_type="MedicationRequest",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert len(result) == 5

    @responses.activate
    def test_filters_entries_by_resource_type(self):
        entries = [
            {"resourceType": "MedicationRequest", "id": "med-1", "status": "active"},
            {"resourceType": "OperationOutcome", "id": "oo-1"},
        ]
        responses.get(
            f"{BASE_URL}/MedicationRequest",
            json=_bundle(entries),
            status=200,
        )
        result = search_resources(
            resource_type="MedicationRequest",
            params={"patient": "p-123"},
            base_url=BASE_URL,
            access_token=TOKEN,
        )
        assert len(result) == 1
        assert result[0]["resourceType"] == "MedicationRequest"
