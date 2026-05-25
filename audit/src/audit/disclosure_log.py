"""HIPAA accounting-of-disclosures.

Writes one S3 object per FHIR call. Schema is deliberately small and
PHI-free: practice_id, call_id, tool, query_template (a *pattern* like
``Patient?telecom=<phone>&birthdate=<dob>``, never the values),
result_resource_ids, disclosed_fields, timestamp.

The bucket is created by infra/lib/audit-stack.ts with Object Lock
(compliance mode) + KMS-CMK + public-access-block. This module only
PutObject's — never reads, never deletes. Compliance role reads,
nothing else.

Configuration (Lambda env vars; CDK injects):
  AUDIT_BUCKET_NAME   required
  AUDIT_KMS_KEY_ARN   optional — used as SSEKMSKeyId when set
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3

_PHONE_RE = re.compile(r"\b\d{7,}\b")
_DOB_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class AuditConfigError(RuntimeError):
    """Required configuration (env var or AWS client) missing."""


class PhiLeakError(RuntimeError):
    """The caller passed raw PHI where a *pattern* was required.

    See module docstring: ``query_template`` must be the format string,
    not the substituted value.
    """


def record(
    *,
    practice_id: str,
    call_id: str,
    tool: str,
    query_template: str,
    result_resource_ids: list[str],
    disclosed_fields: list[str],
) -> str:
    """Write one audit record. Returns the S3 key written.

    Raises ``PhiLeakError`` if ``query_template`` contains an obvious raw
    value (long digit run or YYYY-MM-DD). Defensive only; the real
    contract is that callers pass a format pattern.
    """
    if _PHONE_RE.search(query_template) or _DOB_RE.search(query_template):
        raise PhiLeakError(
            "query_template appears to contain raw PHI; pass a pattern "
            f"like 'Patient?telecom=<phone>' instead of {query_template!r}"
        )

    bucket = os.environ.get("AUDIT_BUCKET_NAME")
    if not bucket:
        raise AuditConfigError("AUDIT_BUCKET_NAME env var not set")

    now = datetime.now(tz=timezone.utc)
    record_id = uuid.uuid4().hex
    key = (
        f"practice_id={practice_id}/"
        f"date={now.date().isoformat()}/"
        f"{now.strftime('%H%M%S')}-{record_id}.json"
    )

    body = {
        "practice_id": practice_id,
        "call_id": call_id,
        "timestamp": now.isoformat(),
        "tool": tool,
        "query_template": query_template,
        "result_resource_ids": list(result_resource_ids),
        "disclosed_fields": list(disclosed_fields),
    }

    put_kwargs: dict = {
        "Bucket": bucket,
        "Key": key,
        "Body": json.dumps(body, separators=(",", ":")).encode(),
        "ContentType": "application/json",
    }
    kms_arn = os.environ.get("AUDIT_KMS_KEY_ARN")
    if kms_arn:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = kms_arn

    s3 = boto3.client("s3")
    s3.put_object(**put_kwargs)
    return key
