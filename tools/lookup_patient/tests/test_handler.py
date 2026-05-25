"""Tests for the lookup_patient Lambda handler.

The handler is fed by:
  - PracticesStore (DDB)            — per-practice config
  - TokenStore (DDB + KMS)          — per-practice OAuth tokens
  - Secrets Manager                  — PF client_secret per ARN
  - DDB rate-limit table             — per-(practice, ANI) daily budget
  - S3 audit bucket                  — one record per FHIR probe
  - Real HTTP to PF (mocked here)    — search_patient probes

Tests use moto for the AWS plane and `responses` for the FHIR plane.
A shared fixture seeds a known-good practice + access token in moto,
sets all env vars CDK would set in production, and yields. Per-test
helpers override specific pieces (no-credentials, expiring token,
invalid_grant, rate-limit-exhausted).
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
import responses
from moto import mock_aws

from lookup_patient.handler import handler

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://qa-api.practicefusion.com/fhir/r4/v1/test-practice"
TOKEN_ENDPOINT = f"{BASE}/token"
PRACTICE_ID = "pf-001"
CALL_ID = "contact-abc-123"

PRACTICES_TABLE = "practices-test"
TOKENS_TABLE = "tokens-test"
RATELIMIT_TABLE = "rate-limit-test"
AUDIT_BUCKET = "audit-test"
OAUTH_KEY_ALIAS = "alias/oauth-test"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# Enrichment Patient.read fixture for the single-candidate bundle. Most
# tests in this file end up with the canonical single match — they all
# need a Patient.read mock now that the handler does the fan-out
# (Session 0009).
_SINGLE_PATIENT_ID = "b79082d9-548c-454e-9fc7-ce19ab630776"
_SINGLE_PATIENT_READ = {
    "resourceType": "Patient",
    "id": _SINGLE_PATIENT_ID,
    "name": [{"family": "Durve", "given": ["Mohit", "Milind"]}],
    "telecom": [{"system": "phone", "use": "mobile", "value": "(716) 361-9276"}],
    "birthDate": "1991-06-09",
}


def _mock_single_patient_read(times: int = 1) -> None:
    for _ in range(times):
        responses.add(
            responses.GET,
            f"{BASE}/Patient/{_SINGLE_PATIENT_ID}",
            json=_SINGLE_PATIENT_READ,
            status=200,
        )


def _bootstrap_aws(*, expires_at: int = 9_999_999_999) -> None:
    """Create all AWS plumbing the handler expects, and seed one practice."""
    kms = boto3.client("kms", region_name="us-east-1")
    cmk = kms.create_key(Description="oauth-test")["KeyMetadata"]["KeyId"]
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
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n, _ in schema],
            BillingMode="PAY_PER_REQUEST",
        )

    sm = boto3.client("secretsmanager", region_name="us-east-1")
    secret_arn = sm.create_secret(
        Name="pf-voice-test/practice/pf-001/pf_client_secret",
        SecretString="test-client-secret",
    )["ARN"]

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=AUDIT_BUCKET)

    # Seed practices row
    ddb.put_item(
        TableName=PRACTICES_TABLE,
        Item={
            "practice_id": {"S": PRACTICE_ID},
            "fhir_base_url": {"S": BASE},
            "token_endpoint": {"S": TOKEN_ENDPOINT},
            "pf_client_id": {"S": "client-abc"},
            "pf_client_secret_arn": {"S": secret_arn},
        },
    )

    # Seed token store via the real TokenStore (encrypts through moto KMS)
    from oauth.token_store import TokenStore

    TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).put(
        PRACTICE_ID,
        access_token="seed-access-token",
        refresh_token="seed-refresh-token",
        expires_at=expires_at,
    )


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRACTICES_TABLE_NAME", PRACTICES_TABLE)
    monkeypatch.setenv("TOKENS_TABLE_NAME", TOKENS_TABLE)
    monkeypatch.setenv("OAUTH_KMS_KEY_ARN", OAUTH_KEY_ALIAS)
    monkeypatch.setenv("RATELIMIT_TABLE_NAME", RATELIMIT_TABLE)
    monkeypatch.setenv("AUDIT_BUCKET_NAME", AUDIT_BUCKET)
    monkeypatch.setenv("RATELIMIT_PER_DAY", "100")
    with mock_aws():
        _bootstrap_aws()
        yield


def _event(**overrides) -> dict:
    """ADR-0013 slim-refactor shape: caller_phone / date_of_birth +
    optional name fields."""
    base = {
        "practice_id": PRACTICE_ID,
        "call_id": CALL_ID,
        "caller_phone": "7163619276",
        "date_of_birth": "1991-06-09",
    }
    base.update(overrides)
    return base


@responses.activate
def test_handler_returns_single_candidate(aws_env):
    responses.add(
        responses.GET, f"{BASE}/Patient", json=_load("bundle_single.json"), status=200
    )
    _mock_single_patient_read()
    result = handler(_event(), None)
    assert result["status"] == "candidates"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["patient_id"] == _SINGLE_PATIENT_ID
    assert result["candidates"][0]["probe_origin"]  # winning probe surfaced


@responses.activate
def test_candidates_carry_enrichment_fields(aws_env):
    """Session 0009 first failing test: every returned candidate carries
    name_first, name_last, date_of_birth, phone_masked sourced from a
    per-candidate ``Patient.read`` fan-out. The search bundle gives us
    only the ids; the agent reasons over the enriched candidates.
    """
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json=_load("bundle_multiple.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/Patient/patient-a",
        json={
            "resourceType": "Patient",
            "id": "patient-a",
            "name": [{"family": "Smith", "given": ["John", "Q."]}],
            "telecom": [{"system": "phone", "value": "(716) 361-9276"}],
            "birthDate": "1991-06-09",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/Patient/patient-b",
        json={
            "resourceType": "Patient",
            "id": "patient-b",
            "name": [{"family": "Smith", "given": ["Jane"]}],
            "telecom": [{"system": "phone", "value": "(716) 555-0124"}],
            "birthDate": "1992-02-02",
        },
        status=200,
    )

    result = handler(_event(), None)
    assert result["status"] == "candidates"
    assert len(result["candidates"]) == 2

    by_id = {c["patient_id"]: c for c in result["candidates"]}
    a = by_id["patient-a"]
    assert a["name_first"] == "John"
    assert a["name_last"] == "Smith"
    assert a["date_of_birth"] == "1991-06-09"
    assert a["phone_masked"] == "9276"
    assert a["probe_origin"]  # winning probe still surfaced

    b = by_id["patient-b"]
    assert b["name_first"] == "Jane"
    assert b["name_last"] == "Smith"
    assert b["date_of_birth"] == "1992-02-02"
    assert b["phone_masked"] == "0124"


@responses.activate
def test_handler_returns_empty_candidates_on_no_match(aws_env):
    for _ in range(6):
        responses.add(
            responses.GET, f"{BASE}/Patient", json=_load("bundle_empty.json"), status=200
        )
    result = handler(_event(), None)
    assert result["status"] == "candidates"
    assert result["candidates"] == []


def test_handler_rejects_missing_call_id(aws_env):
    with pytest.raises(ValueError, match="call_id"):
        handler(
            {
                "practice_id": "pf-001",
                "caller_phone": "7163619276",
                "date_of_birth": "1991-06-09",
            },
            None,
        )


def test_handler_rejects_missing_practice_id(aws_env):
    with pytest.raises(ValueError):
        handler(
            {
                "caller_phone": "7163619276",
                "date_of_birth": "1991-06-09",
                "call_id": CALL_ID,
            },
            None,
        )


def test_handler_rejects_missing_caller_phone(aws_env):
    with pytest.raises(ValueError):
        handler(
            {
                "practice_id": "pf-001",
                "date_of_birth": "1991-06-09",
                "call_id": CALL_ID,
            },
            None,
        )


@responses.activate
def test_emits_one_audit_record_per_fhir_probe(aws_env):
    """The first failing test that opened Session 0006 — still binding
    after the ADR-0013 slim refactor."""
    for _ in range(6):
        responses.add(
            responses.GET, f"{BASE}/Patient", json=_load("bundle_empty.json"), status=200
        )
    result = handler(_event(), None)

    assert result["status"] == "candidates"
    assert result["candidates"] == []
    s3 = boto3.client("s3", region_name="us-east-1")
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=AUDIT_BUCKET).get("Contents", [])]
    assert len(keys) == len(result["probes_tried"])

    # PHI invariant: no audit object body or key contains raw phone or DOB.
    for k in keys:
        assert "7163619276" not in k
        assert "1991-06-09" not in k
        body = json.loads(s3.get_object(Bucket=AUDIT_BUCKET, Key=k)["Body"].read())
        assert "7163619276" not in json.dumps(body)
        assert "1991-06-09" not in json.dumps(body)
        assert body["practice_id"] == PRACTICE_ID
        assert body["call_id"] == CALL_ID
        assert body["tool"] == "lookup_patient"


@responses.activate
def test_rate_limit_exhausted_returns_rate_limited(aws_env, monkeypatch):
    monkeypatch.setenv("RATELIMIT_PER_DAY", "1")
    responses.add(
        responses.GET, f"{BASE}/Patient", json=_load("bundle_single.json"), status=200
    )
    _mock_single_patient_read()

    # First call burns the budget.
    first = handler(_event(), None)
    assert first["status"] == "candidates"
    assert len(first["candidates"]) == 1

    # Second call is rate-limited — same shape, never reaches FHIR.
    second = handler(_event(), None)
    assert second["status"] == "rate_limited"
    assert second["candidates"] == []
    assert second["probes_tried"] == []


@responses.activate
def test_401_triggers_one_refresh_and_retry(aws_env):
    """First probe returns 401; handler refreshes; same probe re-issued with the
    new token returns 200. PF refresh endpoint is mocked.
    """
    responses.add(
        responses.GET,
        f"{BASE}/Patient",
        json={"resourceType": "OperationOutcome", "issue": []},
        status=401,
    )
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={
            "access_token": "refreshed-access-token",
            "refresh_token": "seed-refresh-token",  # non-rotating
            "expires_in": 300,
            "token_type": "Bearer",
            "scope": "user/Patient.read",
        },
        status=200,
    )
    responses.add(
        responses.GET, f"{BASE}/Patient", json=_load("bundle_single.json"), status=200
    )
    _mock_single_patient_read()

    result = handler(_event(), None)
    assert result["status"] == "candidates"
    assert len(result["candidates"]) == 1

    # Token store should reflect the refreshed access token.
    from oauth.token_store import TokenStore

    rec = TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).get(PRACTICE_ID)
    assert rec is not None
    assert rec.access_token == "refreshed-access-token"
    assert rec.refresh_token == "seed-refresh-token"  # unchanged → update_access_token path


@responses.activate
def test_invalid_grant_marks_needs_reconnect(aws_env):
    """Forced refresh returns 400 invalid_grant → status flipped, handler returns
    match='credentials_expired'."""
    # Force the refresh path by writing a near-expired access token.
    import time as _time

    from oauth.token_store import TokenStore

    TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).put(
        PRACTICE_ID,
        access_token="near-dead",
        refresh_token="seed-refresh-token",
        expires_at=int(_time.time()) + 5,  # well within leeway
    )
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_grant", "error_description": "revoked"},
        status=400,
    )

    result = handler(_event(), None)
    assert result["status"] == "credentials_expired"

    rec = TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).get(PRACTICE_ID)
    assert rec is not None
    assert rec.status == "needs_reconnect"


@responses.activate
def test_rotation_persists_new_refresh_token(aws_env):
    """If a refresh response includes a NEW refresh_token, both columns
    are written back via put (defensive path — Session 0004 found PF
    doesn't rotate, but our code handles it if PF starts to).
    """
    import time as _time

    from oauth.token_store import TokenStore

    TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).put(
        PRACTICE_ID,
        access_token="near-dead",
        refresh_token="seed-refresh-token",
        expires_at=int(_time.time()) + 5,
    )
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={
            "access_token": "rot-access",
            "refresh_token": "rot-refresh-NEW",
            "expires_in": 300,
            "token_type": "Bearer",
            "scope": "user/Patient.read",
        },
        status=200,
    )
    responses.add(
        responses.GET, f"{BASE}/Patient", json=_load("bundle_single.json"), status=200
    )
    _mock_single_patient_read()

    result = handler(_event(), None)
    assert result["status"] == "candidates"
    assert len(result["candidates"]) == 1

    rec = TokenStore(
        table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1"
    ).get(PRACTICE_ID)
    assert rec is not None
    assert rec.access_token == "rot-access"
    assert rec.refresh_token == "rot-refresh-NEW"
