"""Lambda entrypoint for the fhir_query tool.

Accepts a resource type + filters from the code-hook Lambda, enforces
allowlists, queries FHIR, applies voice-safe projections, and logs
the audit disclosure.
"""

from __future__ import annotations

import logging
from typing import Any

from audit import disclosure_log
from oauth.credentials import CredentialsExpired, get_credentials

from .fhir_client import FhirQueryError, search_resources
from .projections import project_resource

log = logging.getLogger(__name__)

_ALLOWED_RESOURCE_TYPES = frozenset({
    "AllergyIntolerance",
    "CarePlan",
    "CareTeam",
    "Condition",
    "DiagnosticReport",
    "DocumentReference",
    "Encounter",
    "Goal",
    "Immunization",
    "MedicationRequest",
    "Observation",
    "Procedure",
})

_ALLOWED_FILTERS = frozenset({
    "status",
    "category",
    "date",
    "_count",
    "_sort",
    "clinical-status",
    "code",
    "intent",
    "encounter",
})

_MAX_COUNT = 10


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    practice_id = event.get("practice_id", "")
    call_id = event.get("call_id", "")
    patient_id = event.get("patient_id", "")
    resource_type = event.get("resource_type", "")
    filters = event.get("filters") or {}

    if not patient_id:
        return _error("patient_id is required — caller must be verified first")

    if resource_type not in _ALLOWED_RESOURCE_TYPES:
        return _error(
            f"{resource_type!r} is not an allowed resource type. "
            f"Allowed: {sorted(_ALLOWED_RESOURCE_TYPES)}"
        )

    bad_params = set(filters.keys()) - _ALLOWED_FILTERS
    if bad_params:
        return _error(f"Disallowed search params: {sorted(bad_params)}")

    params: dict[str, str] = {"patient": patient_id}
    for k, v in filters.items():
        if k == "_count":
            params["_count"] = str(min(int(v), _MAX_COUNT))
        else:
            params[k] = str(v)
    if "_count" not in params:
        params["_count"] = str(_MAX_COUNT)

    try:
        base_url, access_token, refresh_ctx = get_credentials(practice_id)
    except CredentialsExpired:
        log.warning("fhir_query.credentials_expired", extra={
            "practice_id": practice_id, "call_id": call_id,
        })
        return {"status": "credentials_expired", "results": []}

    try:
        raw_resources = search_resources(
            resource_type=resource_type,
            params=params,
            base_url=base_url,
            access_token=access_token,
            refresh_access_token=refresh_ctx,
        )
    except FhirQueryError:
        log.exception("fhir_query.fhir_error", extra={
            "practice_id": practice_id, "call_id": call_id,
        })
        return _error("FHIR query failed")

    result_ids = [r.get("id", "") for r in raw_resources]

    disclosure_log.record(
        practice_id=practice_id,
        call_id=call_id,
        tool="fhir_query",
        query_template=f"{resource_type}?patient=<id>&<filters>",
        result_resource_ids=result_ids,
        disclosed_fields=["projected_summary"],
    )

    projected = [project_resource(r) for r in raw_resources]

    log.info("fhir_query", extra={
        "practice_id": practice_id,
        "call_id": call_id,
        "resource_type": resource_type,
        "result_count": len(projected),
    })

    return {"status": "success", "results": projected, "total": len(projected)}


def _error(msg: str) -> dict[str, Any]:
    return {"status": "error", "error": msg, "results": []}
