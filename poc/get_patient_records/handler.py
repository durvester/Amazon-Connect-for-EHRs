"""POC: get_patient_records action group Lambda for Bedrock Agent.

Self-contained — no shared modules. Inline FHIR auth + voice-safe projections.
"""

import json
import os
import re
import time

import boto3
import requests

_ddb = boto3.client("dynamodb")
_kms = boto3.client("kms")
_sm = boto3.client("secretsmanager")

PRACTICES_TABLE = os.environ.get("PRACTICES_TABLE", "pf-voice-qa-practices")
TOKENS_TABLE = os.environ.get("TOKENS_TABLE", "pf-voice-qa-oauth-tokens")
KMS_KEY_ARN = os.environ.get("KMS_KEY_ARN", "")
FHIR_TIMEOUT = 5.0

ALLOWED_TYPES = {
    "Condition", "MedicationRequest", "DiagnosticReport", "Encounter",
    "AllergyIntolerance", "Immunization", "Observation", "Procedure",
    "DocumentReference", "CarePlan", "CareTeam", "Goal",
}


def handler(event, context):
    params = {p["name"]: p["value"] for p in event.get("parameters", []) if "value" in p}
    session = event.get("sessionAttributes", {})
    pf_org_uuid = session.get("pf_org_uuid", "")
    patient_id = params.get("patient_id", "")
    resource_type = params.get("resource_type", "")
    filters = params.get("filters", "")

    if resource_type not in ALLOWED_TYPES:
        body = json.dumps({"error": f"Unsupported resource type: {resource_type}", "records": []})
    elif not patient_id:
        body = json.dumps({"error": "patient_id is required", "records": []})
    else:
        try:
            base_url, token = _get_fhir_credentials(pf_org_uuid)
            records = _query_records(base_url, token, patient_id, resource_type, filters)
            body = json.dumps({"records": records, "count": len(records), "resource_type": resource_type})
        except Exception as e:
            body = json.dumps({"error": str(e), "records": [], "count": 0})

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "function": event.get("function", ""),
            "functionResponse": {"responseBody": {"TEXT": {"body": body}}},
        },
        "sessionAttributes": session,
        "promptSessionAttributes": event.get("promptSessionAttributes", {}),
    }


def _get_fhir_credentials(practice_id):
    row = _ddb.get_item(TableName=PRACTICES_TABLE, Key={"practice_id": {"S": practice_id}})
    item = row.get("Item", {})
    base_url = item.get("fhir_base_url", {}).get("S", "")
    token_endpoint = item.get("token_endpoint", {}).get("S", "")
    client_id = item.get("pf_client_id", {}).get("S", "")
    secret_arn = item.get("pf_client_secret_arn", {}).get("S", "")

    tok_row = _ddb.get_item(TableName=TOKENS_TABLE, Key={"practice_id": {"S": practice_id}})
    tok = tok_row.get("Item", {})
    ct = tok.get("access_token_ciphertext", {}).get("B", b"")
    expires_at = int(tok.get("expires_at", {}).get("N", "0"))
    access_token = _kms.decrypt(CiphertextBlob=ct, KeyId=KMS_KEY_ARN)["Plaintext"].decode()

    if expires_at - int(time.time()) < 60:
        rt_ct = tok.get("refresh_token_ciphertext", {}).get("B", b"")
        refresh_token = _kms.decrypt(CiphertextBlob=rt_ct, KeyId=KMS_KEY_ARN)["Plaintext"].decode()
        client_secret = _sm.get_secret_value(SecretId=secret_arn)["SecretString"]
        access_token, new_expires = _refresh(token_endpoint, client_id, client_secret, refresh_token)
        new_ct = _kms.encrypt(KeyId=KMS_KEY_ARN, Plaintext=access_token.encode())["CiphertextBlob"]
        _ddb.update_item(
            TableName=TOKENS_TABLE,
            Key={"practice_id": {"S": practice_id}},
            UpdateExpression="SET access_token_ciphertext = :ct, expires_at = :ex",
            ExpressionAttributeValues={":ct": {"B": new_ct}, ":ex": {"N": str(new_expires)}},
        )

    return base_url, access_token


def _refresh(token_endpoint, client_id, client_secret, refresh_token):
    resp = requests.post(token_endpoint, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], int(time.time()) + data.get("expires_in", 3600)


def _query_records(base_url, token, patient_id, resource_type, filters_str):
    url = base_url.rstrip("/") + f"/{resource_type}"
    params = {"patient": patient_id, "_count": "10"}
    if filters_str:
        for f in filters_str.split("&"):
            if "=" in f:
                k, v = f.split("=", 1)
                params[k.strip()] = v.strip()

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"}
    resp = requests.get(url, params=params, headers=headers, timeout=FHIR_TIMEOUT)
    resp.raise_for_status()
    bundle = resp.json()

    results = []
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        projected = _project(r, resource_type)
        if projected:
            results.append(projected)
    return results


def _project(resource, resource_type):
    """Extract voice-safe fields only. Never lab values, dosages, or codes."""
    rid = resource.get("id", "")
    match resource_type:
        case "Condition":
            return {"id": rid, "name": _code_display(resource), "status": resource.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", ""), "recorded_date": resource.get("recordedDate", "")}
        case "MedicationRequest":
            med = resource.get("medicationCodeableConcept", {})
            return {"id": rid, "medication": _code_display_from(med), "status": resource.get("status", ""), "date": resource.get("authoredOn", "")}
        case "DiagnosticReport":
            return {"id": rid, "name": _code_display(resource), "status": resource.get("status", ""), "date": resource.get("effectiveDateTime", resource.get("issued", "")), "category": _category(resource)}
        case "Encounter":
            types = resource.get("type", [])
            type_name = _code_display_from(types[0]) if types else ""
            return {"id": rid, "type": type_name, "status": resource.get("status", ""), "date": resource.get("period", {}).get("start", "")}
        case "AllergyIntolerance":
            return {"id": rid, "substance": _code_display(resource), "status": resource.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", ""), "category": ",".join(resource.get("category", []))}
        case "Immunization":
            return {"id": rid, "vaccine": _code_display_from(resource.get("vaccineCode", {})), "date": resource.get("occurrenceDateTime", ""), "status": resource.get("status", "")}
        case "Observation":
            return {"id": rid, "name": _code_display(resource), "status": resource.get("status", ""), "date": resource.get("effectiveDateTime", ""), "category": _category(resource)}
        case "Procedure":
            return {"id": rid, "name": _code_display(resource), "status": resource.get("status", ""), "date": resource.get("performedDateTime", resource.get("performedPeriod", {}).get("start", ""))}
        case "DocumentReference":
            types = resource.get("type", {})
            return {"id": rid, "type": _code_display_from(types), "status": resource.get("status", ""), "date": resource.get("date", "")}
        case "CarePlan":
            return {"id": rid, "title": resource.get("title", _code_display(resource)), "status": resource.get("status", "")}
        case "CareTeam":
            members = [{"name": _practitioner_name(p), "role": _code_display_from(p.get("role", [{}])[0]) if p.get("role") else ""} for p in resource.get("participant", [])]
            return {"id": rid, "members": members, "status": resource.get("status", "")}
        case "Goal":
            return {"id": rid, "description": resource.get("description", {}).get("text", ""), "status": resource.get("lifecycleStatus", "")}
        case _:
            return {"id": rid}


def _code_display(resource):
    code = resource.get("code", {})
    return _code_display_from(code)


def _code_display_from(codeable):
    codings = codeable.get("coding", [])
    if codings and codings[0].get("display"):
        return codings[0]["display"]
    text = codeable.get("text", "")
    if ";" not in text:
        return text
    return codings[0].get("display", "") if codings else ""


def _category(resource):
    cats = resource.get("category", [])
    if cats:
        return _code_display_from(cats[0])
    return ""


def _practitioner_name(participant):
    member = participant.get("member", {})
    return member.get("display", "")
