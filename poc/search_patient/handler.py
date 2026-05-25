"""POC: search_patient action group Lambda for Bedrock Agent.

Self-contained — no shared modules. Inline FHIR auth + phone format probes.
Reads practice credentials from existing DDB tables (pf-voice-qa-practices,
pf-voice-qa-oauth-tokens).
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


def handler(event, context):
    params = {p["name"]: p["value"] for p in event.get("parameters", []) if "value" in p}
    session = event.get("sessionAttributes", {})
    pf_org_uuid = session.get("pf_org_uuid", "")
    caller_phone = params.get("phone") or session.get("caller_phone", "")

    try:
        base_url, token = _get_fhir_credentials(pf_org_uuid)
        candidates = _search_patients(
            base_url, token,
            phone=caller_phone,
            first_name=params.get("first_name", ""),
            last_name=params.get("last_name", ""),
            dob=params.get("date_of_birth", ""),
        )
        body = json.dumps({"patients": candidates, "count": len(candidates)})
    except Exception as e:
        body = json.dumps({"error": str(e), "patients": [], "count": 0})

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


def _search_patients(base_url, token, phone="", first_name="", last_name="", dob=""):
    url = base_url.rstrip("/") + "/Patient"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"}

    if phone:
        for fmt in _phone_formats(phone):
            params = {"telecom": fmt}
            if dob:
                params["birthdate"] = dob
            resp = requests.get(url, params=params, headers=headers, timeout=FHIR_TIMEOUT)
            if resp.ok:
                patients = _extract_patients(resp.json())
                if patients:
                    return patients

    if first_name and last_name:
        params = {"given": first_name, "family": last_name}
        if dob:
            params["birthdate"] = dob
        resp = requests.get(url, params=params, headers=headers, timeout=FHIR_TIMEOUT)
        if resp.ok:
            return _extract_patients(resp.json())

    return []


def _phone_formats(raw):
    digits = re.sub(r"\D", "", raw.lstrip("+"))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return [raw]
    npa, nxx, line = digits[:3], digits[3:6], digits[6:]
    return [
        f"({npa}) {nxx}-{line}",
        f"+1({npa}){nxx}-{line}",
        f"{npa}-{nxx}-{line}",
        f"+1{digits}",
        digits,
    ]


def _extract_patients(bundle):
    results = []
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        if r.get("resourceType") != "Patient":
            continue
        names = r.get("name", [{}])
        given = names[0].get("given", []) if names else []
        phone_digits = ""
        for t in r.get("telecom", []):
            if t.get("system") == "phone" and t.get("value"):
                phone_digits = re.sub(r"\D", "", t["value"])
                break
        results.append({
            "patient_id": r.get("id", ""),
            "first_name": given[0] if given else "",
            "last_name": names[0].get("family", "") if names else "",
            "date_of_birth": r.get("birthDate", ""),
            "phone_last_four": phone_digits[-4:] if phone_digits else "",
        })
    return results
