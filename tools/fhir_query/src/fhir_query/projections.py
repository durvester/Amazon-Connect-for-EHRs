"""Voice-safe FHIR resource projections.

Each function extracts only the fields safe to read aloud over the phone.
Clinical values (lab results, dosages, diagnoses, clinical notes) are
stripped. The code-hook prompt controls what Claude actually says; these
projections are the HIPAA guardrail in code.
"""

from __future__ import annotations

from typing import Any


def project_resource(resource: dict[str, Any]) -> dict[str, Any]:
    rt = resource.get("resourceType", "")
    fn = _PROJECTIONS.get(rt)
    if fn is None:
        raise ValueError(f"Unsupported resource type: {rt!r}")
    return fn(resource)


def project_diagnostic_report(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": r.get("status", ""),
        "category": _first_category_display(r),
        "code_display": _code_text(r),
        "effective_date": _date_only(r.get("effectiveDateTime", "")),
        "issued_date": _date_only(r.get("issued", "")),
        "performer_name": _first_display(r.get("performer")),
    }


def project_medication_request(r: dict[str, Any]) -> dict[str, Any]:
    med_name = ""
    mcc = r.get("medicationCodeableConcept")
    if mcc:
        med_name = mcc.get("text", "") or _first_coding_display(mcc)
    if not med_name:
        med_ref = r.get("medicationReference")
        if med_ref:
            med_name = med_ref.get("display", "")
    return {
        "medication_name": med_name,
        "status": r.get("status", ""),
        "authored_date": _date_only(r.get("authoredOn", "")),
        "requester": _display_or_empty(r.get("requester")),
    }


def project_encounter(r: dict[str, Any]) -> dict[str, Any]:
    enc_type = ""
    types = r.get("type") or []
    if types:
        display = _first_coding_display(types[0])
        if display and display.lower() != "unknown":
            enc_type = display
        elif not display:
            text = types[0].get("text", "")
            if text and ";" not in text and text.lower() != "unknown":
                enc_type = text

    practitioner = ""
    for p in r.get("participant") or []:
        ind = p.get("individual")
        if ind and ind.get("display"):
            practitioner = ind["display"]
            break

    period = r.get("period") or {}
    date = _date_only(period.get("start", ""))

    service_provider = _display_or_empty(r.get("serviceProvider"))

    return {
        "status": r.get("status", ""),
        "type": enc_type,
        "date": date,
        "practitioner_name": practitioner,
        "service_provider": service_provider,
    }


def project_document_reference(r: dict[str, Any]) -> dict[str, Any]:
    doc_type = ""
    t = r.get("type")
    if t:
        doc_type = t.get("text", "") or _first_coding_display(t)

    author = ""
    authors = r.get("author") or []
    if authors:
        author = authors[0].get("display", "")

    return {
        "status": r.get("status", ""),
        "type": doc_type,
        "date": _date_only(r.get("date", "")),
        "description": r.get("description", ""),
        "author": author,
    }


def project_observation(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": r.get("status", ""),
        "code_display": _code_text(r),
        "effective_date": _date_only(r.get("effectiveDateTime", "")),
        "category": _first_category_display(r),
    }


def project_allergy_intolerance(r: dict[str, Any]) -> dict[str, Any]:
    substance = _code_text(r)
    clinical_status = ""
    cs = r.get("clinicalStatus")
    if cs:
        clinical_status = cs.get("text", "") or _first_coding_display(cs)
    return {
        "substance": substance,
        "clinical_status": clinical_status,
        "type": r.get("type", ""),
        "criticality": r.get("criticality", ""),
        "onset_date": _date_only(r.get("onsetDateTime", "")),
        "recorder": _display_or_empty(r.get("recorder")),
    }


def project_condition(r: dict[str, Any]) -> dict[str, Any]:
    clinical_status = ""
    cs = r.get("clinicalStatus")
    if cs:
        clinical_status = cs.get("text", "") or _first_coding_display(cs)
    return {
        "code_display": _code_text(r),
        "clinical_status": clinical_status,
        "category": _first_category_display(r),
        "onset_date": _date_only(r.get("onsetDateTime", "")),
        "abatement_date": _date_only(r.get("abatementDateTime", "")),
    }


def project_immunization(r: dict[str, Any]) -> dict[str, Any]:
    vaccine = ""
    vc = r.get("vaccineCode")
    if vc:
        vaccine = vc.get("text", "") or _first_coding_display(vc)
    performer_name = ""
    for p in r.get("performer") or []:
        actor = p.get("actor")
        if actor and actor.get("display"):
            performer_name = actor["display"]
            break
    return {
        "vaccine_name": vaccine,
        "date": _date_only(r.get("occurrenceDateTime", "")),
        "status": r.get("status", ""),
        "performer_name": performer_name,
        "lot_number": r.get("lotNumber", ""),
    }


def project_procedure(r: dict[str, Any]) -> dict[str, Any]:
    performer_name = ""
    for p in r.get("performer") or []:
        actor = p.get("actor")
        if actor and actor.get("display"):
            performer_name = actor["display"]
            break
    return {
        "code_display": _code_text(r),
        "date": _date_only(r.get("performedDateTime", "") or (r.get("performedPeriod") or {}).get("start", "")),
        "status": r.get("status", ""),
        "performer_name": performer_name,
    }


def project_care_plan(r: dict[str, Any]) -> dict[str, Any]:
    period = r.get("period") or {}
    description = ""
    for cat in r.get("category") or []:
        t = cat.get("text", "")
        if t:
            description = t
            break
    return {
        "status": r.get("status", ""),
        "category": _first_category_display(r),
        "description": r.get("description", "") or description,
        "period_start": _date_only(period.get("start", "")),
        "period_end": _date_only(period.get("end", "")),
    }


def project_care_team(r: dict[str, Any]) -> dict[str, Any]:
    participants = []
    for p in r.get("participant") or []:
        name = ""
        member = p.get("member")
        if member:
            name = member.get("display", "")
        role = ""
        roles = p.get("role") or []
        if roles:
            role = roles[0].get("text", "") or _first_coding_display(roles[0])
        if name:
            participants.append({"name": name, "role": role})
    return {
        "status": r.get("status", ""),
        "participants": participants,
    }


def project_goal(r: dict[str, Any]) -> dict[str, Any]:
    description = ""
    desc = r.get("description")
    if desc:
        description = desc.get("text", "") or _first_coding_display(desc)
    target_date = ""
    targets = r.get("target") or []
    if targets:
        target_date = _date_only(targets[0].get("dueDate", ""))
    return {
        "description": description,
        "status": r.get("lifecycleStatus", ""),
        "start_date": _date_only(r.get("startDate", "")),
        "target_date": target_date,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_only(dt_string: str) -> str:
    if not dt_string:
        return ""
    return dt_string[:10]


def _first_coding_display(codeable_concept: dict[str, Any]) -> str:
    for coding in codeable_concept.get("coding") or []:
        if coding.get("display"):
            return coding["display"]
    return ""


def _code_text(r: dict[str, Any]) -> str:
    code = r.get("code")
    if not code:
        return ""
    display = _first_coding_display(code)
    if display:
        return display
    text = code.get("text", "")
    if ";" in text:
        return ""
    return text


def _first_category_display(r: dict[str, Any]) -> str:
    categories = r.get("category") or []
    if not categories:
        return ""
    return _first_coding_display(categories[0])


def _first_display(items: list | None) -> str:
    if not items:
        return ""
    return items[0].get("display", "")


def _display_or_empty(ref: dict | None) -> str:
    if not ref:
        return ""
    return ref.get("display", "")


_PROJECTIONS = {
    "AllergyIntolerance": project_allergy_intolerance,
    "CarePlan": project_care_plan,
    "CareTeam": project_care_team,
    "Condition": project_condition,
    "DiagnosticReport": project_diagnostic_report,
    "DocumentReference": project_document_reference,
    "Encounter": project_encounter,
    "Goal": project_goal,
    "Immunization": project_immunization,
    "MedicationRequest": project_medication_request,
    "Observation": project_observation,
    "Procedure": project_procedure,
}
