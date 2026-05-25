"""Practice Fusion FHIR Patient-search client.

Encapsulates the PF-specific telecom-search quirk (ADR-0006): we probe a
priority-ordered list of phone formats and stop at the first match.

Session 0006 added two seams:
  - ``on_probe`` callback: invoked after every probe HTTP call (success
    or non-2xx). Used by the handler to write one audit record per
    probe — keeping audit/PHI knowledge out of this module.
  - ``refresh_access_token``: called once on a 401 to mint a fresh
    token. Inverts the "401 retry" concern: the credentials owner
    (handler) decides what "refresh" means; this client just retries.

Both seams are optional. Without them, behavior is identical to
Session 0003.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

import requests

from .normalize import PhoneFormatError, to_pf_phone_formats

_DOB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMEOUT_SECONDS = 5.0
_PHONE_DIGITS_RE = re.compile(r"\D+")

OnProbe = Callable[..., None]              # kw-only: probe, status_code, result_ids
RefreshAccessToken = Callable[[], str]     # returns the new bearer token


def read_patient(
    patient_id: str,
    base_url: str,
    access_token: str,
    *,
    refresh_access_token: Optional[RefreshAccessToken] = None,
) -> dict[str, Any]:
    """Fetch a single Patient by id and return the enrichment fields the
    agent needs. Issues one ``Patient.read`` against PF FHIR with the
    same one-shot 401 refresh-and-retry semantics as ``search_patient``.

    Returns ``{name_first, name_last, date_of_birth, phone_masked}``.
    Missing fields surface as empty strings — the agent's prompt
    decides what to do with partial enrichment.
    """
    url = base_url.rstrip("/") + f"/Patient/{patient_id}"
    token = access_token
    resp = _read_get(url, token)
    if resp.status_code == 401 and refresh_access_token is not None:
        token = refresh_access_token()
        resp = _read_get(url, token)
    if not resp.ok:
        raise FhirClientError(
            f"FHIR Patient.read failed: {resp.status_code} {resp.text[:200]}"
        )
    return _project_enrichment(resp.json())


def _read_get(url: str, token: str) -> requests.Response:
    return requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        timeout=_TIMEOUT_SECONDS,
    )


def _project_enrichment(patient: dict[str, Any]) -> dict[str, Any]:
    name_first = ""
    name_last = ""
    names = patient.get("name") or []
    if names:
        n0 = names[0]
        given = n0.get("given") or []
        name_first = given[0] if given else ""
        name_last = n0.get("family", "") or ""

    phone_masked = ""
    for t in patient.get("telecom") or []:
        if t.get("system") == "phone" and t.get("value"):
            digits = _PHONE_DIGITS_RE.sub("", t["value"])
            phone_masked = digits[-4:] if digits else ""
            break

    return {
        "name_first": name_first,
        "name_last": name_last,
        "date_of_birth": patient.get("birthDate", "") or "",
        "phone_masked": phone_masked,
    }


class FhirClientError(RuntimeError):
    """Raised for any non-2xx response (after 401 retry) or invalid input."""


def search_patient(
    phone: str,
    dob: str,
    base_url: str,
    access_token: str,
    *,
    name_first: Optional[str] = None,
    name_last: Optional[str] = None,
    on_probe: Optional[OnProbe] = None,
    refresh_access_token: Optional[RefreshAccessToken] = None,
) -> dict[str, Any]:
    """Search PF FHIR for a Patient matching ``phone`` and ``dob``.

    When all phone-format probes return zero and ``name_first`` +
    ``name_last`` are provided, falls back to ``family+given+birthdate``
    search (Session 0013).
    """
    if not _DOB_RE.match(dob or ""):
        raise FhirClientError(f"dob must be YYYY-MM-DD, got {dob!r}")

    try:
        probes = to_pf_phone_formats(phone)
    except PhoneFormatError as e:
        raise FhirClientError(str(e)) from e

    tried: list[str] = []
    url = base_url.rstrip("/") + "/Patient"
    token = access_token
    refreshed_once = False

    for probe in probes:
        tried.append(probe)
        resp = _get_with_one_retry(url, probe, dob, token)
        if resp.status_code == 401 and not refreshed_once and refresh_access_token:
            # One-shot refresh-and-retry. After this, 401s are permanent.
            token = refresh_access_token()
            refreshed_once = True
            resp = _get_with_one_retry(url, probe, dob, token)

        if not resp.ok:
            if on_probe is not None:
                on_probe(probe=probe, status_code=resp.status_code, result_ids=[])
            raise FhirClientError(
                f"FHIR Patient search failed: {resp.status_code} {resp.text[:200]}"
            )

        bundle = resp.json()
        ids = [
            e["resource"]["id"]
            for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"
        ]

        if on_probe is not None:
            on_probe(probe=probe, status_code=resp.status_code, result_ids=ids)

        if len(ids) == 1:
            return {
                "match": "single",
                "patient_id": ids[0],
                "candidates": [],
                "probes_tried": tried,
                "winning_format": probe,
            }
        if len(ids) > 1:
            return {
                "match": "multiple",
                "patient_id": None,
                "candidates": ids,
                "probes_tried": tried,
                "winning_format": probe,
            }

    if name_first and name_last:
        tried.append("name+dob")
        resp = _get_name_search(url, name_last, name_first, dob, token)
        if resp.status_code == 401 and not refreshed_once and refresh_access_token:
            token = refresh_access_token()
            refreshed_once = True
            resp = _get_name_search(url, name_last, name_first, dob, token)

        if not resp.ok:
            if on_probe is not None:
                on_probe(probe="name+dob", status_code=resp.status_code, result_ids=[])
            raise FhirClientError(
                f"FHIR Patient name search failed: {resp.status_code} {resp.text[:200]}"
            )

        bundle = resp.json()
        ids = [
            e["resource"]["id"]
            for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"
        ]
        if on_probe is not None:
            on_probe(probe="name+dob", status_code=resp.status_code, result_ids=ids)

        if len(ids) == 1:
            return {
                "match": "single",
                "patient_id": ids[0],
                "candidates": [],
                "probes_tried": tried,
                "winning_format": "name+dob",
            }
        if len(ids) > 1:
            return {
                "match": "multiple",
                "patient_id": None,
                "candidates": ids,
                "probes_tried": tried,
                "winning_format": "name+dob",
            }

    return {
        "match": "none",
        "patient_id": None,
        "candidates": [],
        "probes_tried": tried,
        "winning_format": None,
    }


def search_patient_by_phone(
    phone: str,
    base_url: str,
    access_token: str,
    *,
    on_probe: Optional[OnProbe] = None,
    refresh_access_token: Optional[RefreshAccessToken] = None,
) -> dict[str, Any]:
    """Search PF FHIR for Patient by phone only (no DOB).

    Used for proactive caller identification on the first turn — we have
    the ANI before the caller says anything.
    """
    try:
        probes = to_pf_phone_formats(phone)
    except PhoneFormatError as e:
        raise FhirClientError(str(e)) from e

    tried: list[str] = []
    url = base_url.rstrip("/") + "/Patient"
    token = access_token
    refreshed_once = False

    for probe in probes:
        tried.append(probe)
        resp = _get_phone_only(url, probe, token)
        if resp.status_code == 401 and not refreshed_once and refresh_access_token:
            token = refresh_access_token()
            refreshed_once = True
            resp = _get_phone_only(url, probe, token)

        if not resp.ok:
            if on_probe is not None:
                on_probe(probe=probe, status_code=resp.status_code, result_ids=[])
            raise FhirClientError(
                f"FHIR Patient phone search failed: {resp.status_code} {resp.text[:200]}"
            )

        bundle = resp.json()
        ids = [
            e["resource"]["id"]
            for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"
        ]

        if on_probe is not None:
            on_probe(probe=probe, status_code=resp.status_code, result_ids=ids)

        if len(ids) == 1:
            return {"match": "single", "patient_id": ids[0], "candidates": [], "probes_tried": tried, "winning_format": probe}
        if len(ids) > 1:
            return {"match": "multiple", "patient_id": None, "candidates": ids, "probes_tried": tried, "winning_format": probe}

    return {"match": "none", "patient_id": None, "candidates": [], "probes_tried": tried, "winning_format": None}


def _get_phone_only(url: str, probe: str, token: str) -> requests.Response:
    return requests.get(
        url,
        params={"telecom": probe},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"},
        timeout=_TIMEOUT_SECONDS,
    )


def _get_name_search(
    url: str, family: str, given: str, dob: str, token: str
) -> requests.Response:
    return requests.get(
        url,
        params={"family": family, "given": given, "birthdate": dob},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        timeout=_TIMEOUT_SECONDS,
    )


def _get_with_one_retry(url: str, probe: str, dob: str, token: str) -> requests.Response:
    return requests.get(
        url,
        params={"telecom": probe, "birthdate": dob},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        timeout=_TIMEOUT_SECONDS,
    )
