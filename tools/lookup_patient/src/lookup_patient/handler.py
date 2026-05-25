"""Lambda entrypoint for the ``lookup_patient`` tool.

Session 0007 slim refactor (ADR-0013): the handler is a thin FHIR adapter.
Verification reasoning lives in the Connect AI agent prompt, not here.
The handler:

  - Accepts caller-collected identity inputs + the contact-flow-set
    ``practice_id`` (ADR-0014).
  - Runs the per-(practice, ANI) rate-limit gate first (ADR-0009).
  - Resolves per-practice credentials (refreshes transparently on
    near-expiry or 401).
  - Issues PF Patient.search probes (literal telecom format, ADR-0006).
  - Writes one audit-disclosure record per FHIR probe (ADR-0009).
  - Returns a candidate list (status="candidates" with possibly zero
    items) OR a non-success status. The agent reasons over the result.

Event shape (matches ``tools/lookup_patient/tool_schema.json``):
    {
      "practice_id": str,        # required — set by contact flow
      "call_id": str,            # required — Connect contact id
      "caller_phone": str,       # required — E.164 ANI
      "name_first": str?,        # optional — agent-collected
      "name_last": str?,         # optional — agent-collected
      "date_of_birth": str?,     # optional — agent-collected, YYYY-MM-DD
    }

Return shape:
    {
      "status": "candidates" | "rate_limited" | "credentials_expired" | "error",
      "candidates": [{"patient_id": str, "probe_origin": str}, ...],
      "probes_tried": [str],
    }

``name_first`` / ``name_last`` are accepted today and ignored by the
underlying FHIR client; name-search probes land in a later session.
Per-candidate enrichment (name, dob, phone_masked) is also a later
session — Session 0009's first real call uses the current candidate
shape (patient_id only) and the agent asks a confirmation question
keyed on patient_id.

Configuration (Lambda env vars; CDK injects per ADR-0008):
  PRACTICES_TABLE_NAME       required
  TOKENS_TABLE_NAME          required
  OAUTH_KMS_KEY_ARN          required
  AUDIT_BUCKET_NAME          required
  RATELIMIT_TABLE_NAME       required
  RATELIMIT_PER_DAY          optional (default 100)
  AWS_REGION                 (provided by Lambda runtime)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from audit import disclosure_log
from audit.rate_limit import RateLimitExceeded, check_and_increment
from oauth.credentials import CredentialsExpired, get_credentials

from .fhir_client import FhirClientError, read_patient, search_patient, search_patient_by_phone

_REQUIRED_FIELDS = ("practice_id", "call_id", "caller_phone")
log = logging.getLogger(__name__)


def _make_audit_callback(*, practice_id: str, call_id: str):
    def cb(*, probe: str, status_code: int, result_ids: list[str]) -> None:
        del probe, status_code  # PHI / not in audit schema
        disclosure_log.record(
            practice_id=practice_id,
            call_id=call_id,
            tool="lookup_patient",
            query_template="Patient?telecom=<phone>&birthdate=<dob>",
            result_resource_ids=result_ids,
            disclosed_fields=["id"],
        )

    return cb


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    missing = [f for f in _REQUIRED_FIELDS if not event.get(f)]
    if missing:
        raise ValueError(f"missing required fields: {missing}")

    practice_id = event["practice_id"]
    call_id = event["call_id"]
    caller_phone = event["caller_phone"]
    date_of_birth = event.get("date_of_birth", "")

    # Rate-limit gate first. Indistinguishable from a real not-found
    # outcome on the wire (ADR-0009 — leak-resistance).
    max_per_day = int(os.environ.get("RATELIMIT_PER_DAY", "100"))
    try:
        check_and_increment(
            practice_id=practice_id, ani=caller_phone, max_per_day=max_per_day
        )
    except RateLimitExceeded:
        log.warning(
            "lookup_patient.rate_limited",
            extra={"practice_id": practice_id, "call_id": call_id},
        )
        return _result("rate_limited", probes_tried=[])

    try:
        base_url, access_token, refresh_ctx = get_credentials(practice_id)
    except CredentialsExpired:
        log.warning(
            "lookup_patient.credentials_expired",
            extra={"practice_id": practice_id, "call_id": call_id},
        )
        return _result("credentials_expired", probes_tried=[])

    audit_cb = _make_audit_callback(practice_id=practice_id, call_id=call_id)

    name_first = event.get("name_first", "") or ""
    name_last = event.get("name_last", "") or ""

    try:
        raw = search_patient(
            caller_phone,
            date_of_birth,
            base_url,
            access_token,
            name_first=name_first or None,
            name_last=name_last or None,
            on_probe=audit_cb,
            refresh_access_token=refresh_ctx,
        )
    except FhirClientError:
        log.exception(
            "lookup_patient.fhir_error",
            extra={"practice_id": practice_id, "call_id": call_id},
        )
        raise

    # Translate the fhir_client's match/none/multiple verdict into the
    # candidates-list shape the agent (ADR-0013) consumes, then enrich
    # each candidate with a Patient.read fan-out (Session 0007 OQ #3)
    # so the agent has {name_first, name_last, date_of_birth,
    # phone_masked} to disambiguate over.
    probe_origin = raw.get("winning_format")
    if raw["match"] == "single":
        candidate_ids = [raw["patient_id"]]
    elif raw["match"] == "multiple":
        candidate_ids = list(raw["candidates"])
    else:
        candidate_ids = []

    phone_match_ids: set[str] = set()
    if candidate_ids and caller_phone:
        try:
            phone_raw = search_patient_by_phone(
                caller_phone, base_url, access_token,
                refresh_access_token=refresh_ctx,
            )
            if phone_raw["match"] == "single":
                phone_match_ids.add(phone_raw["patient_id"])
            elif phone_raw["match"] == "multiple":
                phone_match_ids.update(phone_raw["candidates"])
        except FhirClientError:
            pass

    candidates: list[dict[str, Any]] = []
    for pid in candidate_ids:
        enrichment = read_patient(
            pid, base_url, access_token, refresh_access_token=refresh_ctx
        )
        candidates.append({
            "patient_id": pid,
            "probe_origin": probe_origin,
            "phone_match": pid in phone_match_ids,
            **enrichment,
        })

    log.info(
        "lookup_patient",
        extra={
            "practice_id": practice_id,
            "call_id": call_id,
            "candidate_count": len(candidates),
            "probes_count": len(raw["probes_tried"]),
            "winning_format": probe_origin,
        },
    )
    return _result(
        "candidates", candidates=candidates, probes_tried=raw["probes_tried"]
    )


def _result(
    status: str,
    *,
    candidates: list[dict[str, Any]] | None = None,
    probes_tried: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "candidates": candidates or [],
        "probes_tried": probes_tried,
    }
