#!/usr/bin/env python3
"""Probe a FHIR server for clinical resources of a known patient.

Uses the same credential chain as the live Lambda (DDB + KMS).

Required env vars:
  PF_ORG_UUID          Practice/org identifier
  PATIENT_ID           FHIR Patient resource ID to probe
  PRACTICES_TABLE_NAME DynamoDB practices table
  TOKENS_TABLE_NAME    DynamoDB OAuth tokens table
  OAUTH_KMS_KEY_ARN    KMS key ARN for token decryption

Usage: .venv/bin/python scripts/probe-fhir-resources.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for pkg in ("oauth/src", "tools/lookup_patient/src", "tools/fhir_query/src", "audit/src", "routing/src"):
    sys.path.insert(0, str(REPO / pkg))

import requests

os.environ.setdefault("AWS_REGION", "us-east-1")

from oauth.credentials import get_credentials

PRACTICE_ID = os.environ.get("PF_ORG_UUID")
PATIENT_ID = os.environ.get("PATIENT_ID")

if not PRACTICE_ID or not PATIENT_ID:
    print("Error: PF_ORG_UUID and PATIENT_ID env vars are required.")
    print("  export PF_ORG_UUID=<your-practice-uuid>")
    print("  export PATIENT_ID=<fhir-patient-id>")
    sys.exit(1)

RESOURCES = [
    ("DiagnosticReport", {"patient": PATIENT_ID, "_count": "5"}),
    ("MedicationRequest", {"patient": PATIENT_ID, "_count": "5"}),
    ("Encounter", {"patient": PATIENT_ID, "_count": "5", "_sort": "-date"}),
    ("DocumentReference", {"patient": PATIENT_ID, "_count": "5"}),
    ("Observation", {"patient": PATIENT_ID, "category": "laboratory", "_count": "5"}),
    ("Observation", {"patient": PATIENT_ID, "category": "vital-signs", "_count": "3"}),
]


def probe(token: str, base_url: str, resource_type: str, params: dict) -> dict:
    url = base_url.rstrip("/") + f"/{resource_type}"
    resp = requests.get(
        url,
        params=params,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        timeout=10,
    )
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text[:500]}


def main():
    base_url, token, _ = get_credentials(PRACTICE_ID)
    print(f"Base URL: {base_url}")
    print(f"Patient: {PATIENT_ID}")
    print(f"Token acquired.\n")

    results = {}
    for resource_type, params in RESOURCES:
        label = f"{resource_type}({','.join(f'{k}={v}' for k, v in params.items() if k != 'patient')})"
        print(f"--- {label} ---")
        result = probe(token, base_url, resource_type, params)
        print(f"Status: {result['status_code']}")

        if result["status_code"] == 200:
            body = result["body"]
            total = body.get("total", "?")
            entries = body.get("entry", [])
            print(f"Total: {total}, Entries: {len(entries)}")
            for i, entry in enumerate(entries[:3]):
                r = entry.get("resource", {})
                print(f"\n  [{i}] {r.get('resourceType')}/{r.get('id')}")
                for key in sorted(r.keys()):
                    if key in ("resourceType", "id", "meta", "text"):
                        continue
                    val = r[key]
                    if isinstance(val, str) and len(val) > 150:
                        val = val[:150] + "..."
                    print(f"      {key}: {json.dumps(val, default=str)[:250]}")
            results[label] = body
        else:
            print(f"Error: {result['body'][:300]}")
        print()

    out = REPO / "probe-results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to {out}")


if __name__ == "__main__":
    main()
