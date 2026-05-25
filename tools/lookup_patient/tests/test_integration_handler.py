"""End-to-end handler integration test against live PF QA.

Exercises the full Session-0006 production flow without a network mock:
  rate_limit (moto DDB)
   → _get_credentials (moto KMS+DDB+Secrets Manager + real PF token endpoint)
   → search_patient (real PF QA Patient search)
   → audit (moto S3)

AWS services are all mocked (moto), so the test runs in-process and
needs only the PF QA refresh-token env vars. Real PF QA is hit for
the SMART discovery + refresh-grant + Patient search.

Skipped unless ``PF_FHIR_BASE_URL`` + ``PF_REFRESH_TOKEN`` +
``PF_CLIENT_ID`` + ``PF_CLIENT_SECRET`` are set (provided by the
sealed-box fixture in Session 0005's harness).
"""

from __future__ import annotations

import json
import os
import time

import boto3
import pytest
from moto import mock_aws

pytestmark = pytest.mark.integration

_REQUIRED_ENV = ("PF_FHIR_BASE_URL", "PF_REFRESH_TOKEN", "PF_CLIENT_ID", "PF_CLIENT_SECRET")

PRACTICES_TABLE = "practices-it"
TOKENS_TABLE = "tokens-it"
RATELIMIT_TABLE = "rate-limit-it"
AUDIT_BUCKET = "audit-it"
OAUTH_KEY_ALIAS = "alias/oauth-it"
PRACTICE_ID = "pf-it-001"
CALL_ID = "contact-it-001"
EXPECTED_PATIENT_ID = "b79082d9-548c-454e-9fc7-ce19ab630776"


def _need_env():
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        pytest.skip(f"integration: missing env vars: {missing}")


def test_full_handler_flow_against_pf_qa(monkeypatch):
    """The whole Session-0006 vertical slice, end-to-end against PF QA."""
    _need_env()
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRACTICES_TABLE_NAME", PRACTICES_TABLE)
    monkeypatch.setenv("TOKENS_TABLE_NAME", TOKENS_TABLE)
    monkeypatch.setenv("OAUTH_KMS_KEY_ARN", OAUTH_KEY_ALIAS)
    monkeypatch.setenv("RATELIMIT_TABLE_NAME", RATELIMIT_TABLE)
    monkeypatch.setenv("AUDIT_BUCKET_NAME", AUDIT_BUCKET)
    monkeypatch.setenv("RATELIMIT_PER_DAY", "100")

    fhir_base_url = os.environ["PF_FHIR_BASE_URL"]
    # Discover the per-tenant token endpoint (Session 0004 finding).
    from oauth.well_known import fetch_smart_configuration

    token_endpoint = fetch_smart_configuration(fhir_base_url).token_endpoint

    with mock_aws():
        # AWS plumbing
        kms = boto3.client("kms", region_name="us-east-1")
        cmk = kms.create_key(Description="it")["KeyMetadata"]["KeyId"]
        kms.create_alias(AliasName=OAUTH_KEY_ALIAS, TargetKeyId=cmk)

        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for tname, schema in (
            (PRACTICES_TABLE, [("practice_id", "HASH")]),
            (TOKENS_TABLE, [("practice_id", "HASH")]),
            (RATELIMIT_TABLE, [("pk", "HASH"), ("bucket", "RANGE")]),
        ):
            ddb.create_table(
                TableName=tname,
                KeySchema=[{"AttributeName": n, "KeyType": k} for n, k in schema],
                AttributeDefinitions=[
                    {"AttributeName": n, "AttributeType": "S"} for n, _ in schema
                ],
                BillingMode="PAY_PER_REQUEST",
            )

        sm = boto3.client("secretsmanager", region_name="us-east-1")
        secret_arn = sm.create_secret(
            Name=f"pf-voice-it/practice/{PRACTICE_ID}/pf_client_secret",
            SecretString=os.environ["PF_CLIENT_SECRET"],
        )["ARN"]

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=AUDIT_BUCKET)

        ddb.put_item(
            TableName=PRACTICES_TABLE,
            Item={
                "practice_id": {"S": PRACTICE_ID},
                "fhir_base_url": {"S": fhir_base_url},
                "token_endpoint": {"S": token_endpoint},
                "pf_client_id": {"S": os.environ["PF_CLIENT_ID"]},
                "pf_client_secret_arn": {"S": secret_arn},
            },
        )

        # Seed the token store with a *near-expired* access token so the
        # handler is forced through the refresh-against-real-PF code path.
        from oauth.token_store import TokenStore

        TokenStore(
            table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
        ).put(
            PRACTICE_ID,
            access_token="stale-will-be-refreshed",
            refresh_token=os.environ["PF_REFRESH_TOKEN"],
            expires_at=int(time.time()) + 5,  # within refresh leeway
        )

        from lookup_patient.handler import handler

        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "caller_phone": "7163619276",
                "date_of_birth": "1991-06-09",
                "call_id": CALL_ID,
            },
            None,
        )

        # Slim-refactor shape (ADR-0013): one candidate, no match verdict.
        assert result["status"] == "candidates", result
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["patient_id"] == EXPECTED_PATIENT_ID

        # Audit records: one per probe issued, no PHI in any object.
        s3 = boto3.client("s3", region_name="us-east-1")
        keys = [
            o["Key"]
            for o in s3.list_objects_v2(Bucket=AUDIT_BUCKET).get("Contents", [])
        ]
        assert len(keys) == len(result["probes_tried"])
        for k in keys:
            body = json.loads(s3.get_object(Bucket=AUDIT_BUCKET, Key=k)["Body"].read())
            assert body["practice_id"] == PRACTICE_ID
            assert body["call_id"] == CALL_ID
            assert "7163619276" not in json.dumps(body)
            assert "1991-06-09" not in json.dumps(body)

        # Token store post-state: refresh happened, refresh token unchanged
        # (PF does not rotate — Session 0004 finding).
        rec = TokenStore(
            table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
        ).get(PRACTICE_ID)
        assert rec is not None
        assert rec.status == "active"
        assert rec.access_token != "stale-will-be-refreshed"
        assert rec.refresh_token == os.environ["PF_REFRESH_TOKEN"]
