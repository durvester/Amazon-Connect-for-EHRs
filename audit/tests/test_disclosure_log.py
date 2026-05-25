"""disclosure_log.record writes one S3 object per FHIR call.

PHI invariants enforced at write time, not just at read time:
  - query_template is a *pattern* ("Patient?telecom=<phone>&birthdate=<dob>"),
    never the raw phone/DOB.
  - disclosed_fields names which keys of the resource were read, never the
    values.
  - result_resource_ids is the list of FHIR resource IDs touched.

Schema (S3 object body, JSON):
  practice_id, call_id, timestamp, tool, query_template,
  result_resource_ids, disclosed_fields
"""

from __future__ import annotations

import json
import re

import boto3
import pytest
from moto import mock_aws

BUCKET = "pf-voice-qa-audit"


@pytest.fixture
def audit_bucket(monkeypatch):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        monkeypatch.setenv("AUDIT_BUCKET_NAME", BUCKET)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        yield s3


def test_record_writes_one_object_per_call(audit_bucket):
    from audit.disclosure_log import record

    record(
        practice_id="pf-001",
        call_id="contact-abc",
        tool="lookup_patient",
        query_template="Patient?telecom=<phone>&birthdate=<dob>",
        result_resource_ids=["patient-uuid-1"],
        disclosed_fields=["id"],
    )

    resp = audit_bucket.list_objects_v2(Bucket=BUCKET)
    assert resp["KeyCount"] == 1
    key = resp["Contents"][0]["Key"]
    # Keys are partitioned by practice and date for cheap audits.
    assert key.startswith("practice_id=pf-001/")
    assert re.search(r"date=\d{4}-\d{2}-\d{2}/", key), key

    body = json.loads(audit_bucket.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    assert body["practice_id"] == "pf-001"
    assert body["call_id"] == "contact-abc"
    assert body["tool"] == "lookup_patient"
    assert body["query_template"] == "Patient?telecom=<phone>&birthdate=<dob>"
    assert body["result_resource_ids"] == ["patient-uuid-1"]
    assert body["disclosed_fields"] == ["id"]
    assert body["timestamp"]  # ISO-8601 string


def test_record_rejects_phi_in_query_template(audit_bucket):
    from audit.disclosure_log import PhiLeakError, record

    # The contract: query_template is a pattern, never a real value. We can't
    # detect all PHI, but we can reject obvious raw-digit phone-number leaks
    # and raw YYYY-MM-DD DOB leaks — both indicate the caller passed the
    # wrong argument.
    with pytest.raises(PhiLeakError):
        record(
            practice_id="pf-001",
            call_id="contact-abc",
            tool="lookup_patient",
            query_template="Patient?telecom=7163619276&birthdate=1991-06-09",
            result_resource_ids=[],
            disclosed_fields=[],
        )


def test_record_raises_when_bucket_env_missing(monkeypatch):
    from audit.disclosure_log import AuditConfigError, record

    monkeypatch.delenv("AUDIT_BUCKET_NAME", raising=False)
    with pytest.raises(AuditConfigError):
        record(
            practice_id="pf-001",
            call_id="contact-abc",
            tool="lookup_patient",
            query_template="Patient?telecom=<phone>",
            result_resource_ids=[],
            disclosed_fields=[],
        )


def test_record_multiple_probes_each_get_own_object(audit_bucket):
    from audit.disclosure_log import record

    for _ in range(6):
        record(
            practice_id="pf-001",
            call_id="contact-abc",
            tool="lookup_patient",
            query_template="Patient?telecom=<phone>&birthdate=<dob>",
            result_resource_ids=[],
            disclosed_fields=[],
        )
    resp = audit_bucket.list_objects_v2(Bucket=BUCKET)
    assert resp["KeyCount"] == 6
