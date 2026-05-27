"""Tests for the fhir_query handler — allowlists, verification gate, projections."""

from __future__ import annotations

import boto3
import pytest
import responses
from moto import mock_aws

from fhir_query.handler import handler

PRACTICE_ID = "pf-001"
CALL_ID = "contact-abc-123"
PATIENT_ID = "patient-xyz-789"
FHIR_BASE = "https://qa-api.practicefusion.com/fhir/r4/v1/test-org"

PRACTICES_TABLE = "practices-fq-test"
TOKENS_TABLE = "tokens-fq-test"
OAUTH_KEY_ALIAS = "alias/oauth-fq-test"
AUDIT_BUCKET = "audit-fq-test"


def _bootstrap_aws() -> None:
    kms = boto3.client("kms", region_name="us-east-1")
    cmk = kms.create_key(Description="fq-test")["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName=OAUTH_KEY_ALIAS, TargetKeyId=cmk)

    ddb = boto3.client("dynamodb", region_name="us-east-1")
    for tname in (PRACTICES_TABLE, TOKENS_TABLE):
        ddb.create_table(
            TableName=tname,
            KeySchema=[{"AttributeName": "practice_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "practice_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

    sm = boto3.client("secretsmanager", region_name="us-east-1")
    sm.create_secret(Name="fq-test-secret", SecretString="client-secret-val")

    from oauth.practices_store import PracticesStore
    from oauth.token_store import TokenStore

    ps = PracticesStore(table_name=PRACTICES_TABLE, region="us-east-1")
    ps.put(
        practice_id=PRACTICE_ID,
        fhir_base_url=FHIR_BASE,
        token_endpoint=f"{FHIR_BASE}/token",
        pf_client_id="test-client",
        pf_client_secret_arn="arn:aws:secretsmanager:us-east-1:123456789:secret:fq-test-secret",
    )
    ts = TokenStore(table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1")
    ts.put(
        PRACTICE_ID,
        access_token="valid-token",
        refresh_token="valid-refresh",
        expires_at=9_999_999_999,
    )

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=AUDIT_BUCKET)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("PRACTICES_TABLE_NAME", PRACTICES_TABLE)
    monkeypatch.setenv("TOKENS_TABLE_NAME", TOKENS_TABLE)
    monkeypatch.setenv("OAUTH_KMS_KEY_ARN", OAUTH_KEY_ALIAS)
    monkeypatch.setenv("AUDIT_BUCKET_NAME", AUDIT_BUCKET)


def _bundle(entries: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": [{"resource": e} for e in entries],
    }


def _empty_bundle() -> dict:
    return {"resourceType": "Bundle", "type": "searchset", "total": 0}


class TestVerificationGate:
    @mock_aws
    def test_rejects_without_patient_id(self):
        _bootstrap_aws()
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "resource_type": "DiagnosticReport",
            },
            None,
        )
        assert result["status"] == "error"
        assert "patient_id" in result["error"]

    @mock_aws
    def test_rejects_empty_patient_id(self):
        _bootstrap_aws()
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": "",
                "resource_type": "DiagnosticReport",
            },
            None,
        )
        assert result["status"] == "error"


class TestAllowlist:
    @mock_aws
    def test_rejects_unsupported_resource_type(self):
        _bootstrap_aws()
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "Coverage",
            },
            None,
        )
        assert result["status"] == "error"
        assert "Coverage" in result["error"]

    @mock_aws
    def test_rejects_disallowed_search_param(self):
        _bootstrap_aws()
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "DiagnosticReport",
                "filters": {"_include": "DiagnosticReport:result"},
            },
            None,
        )
        assert result["status"] == "error"
        assert "_include" in result["error"]


class TestSuccessfulQuery:
    @mock_aws
    @responses.activate
    def test_returns_projected_results(self):
        _bootstrap_aws()
        dr = {
            "resourceType": "DiagnosticReport",
            "id": "dr-1",
            "status": "final",
            "category": [{"coding": [{"display": "Laboratory"}]}],
            "code": {"text": "CBC"},
            "effectiveDateTime": "2026-05-20T10:00:00Z",
            "performer": [{"display": "Quest"}],
            "result": [{"reference": "Observation/obs-1"}],
            "conclusion": "Normal",
        }
        responses.get(
            f"{FHIR_BASE}/DiagnosticReport",
            json=_bundle([dr]),
            status=200,
        )
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "DiagnosticReport",
            },
            None,
        )
        assert result["status"] == "success"
        assert len(result["results"]) == 1
        projected = result["results"][0]
        assert projected["status"] == "final"
        assert projected["code_display"] == "CBC"
        assert "result" not in projected
        assert "conclusion" not in projected

    @mock_aws
    @responses.activate
    def test_returns_empty_results(self):
        _bootstrap_aws()
        responses.get(
            f"{FHIR_BASE}/MedicationRequest",
            json=_empty_bundle(),
            status=200,
        )
        result = handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "MedicationRequest",
            },
            None,
        )
        assert result["status"] == "success"
        assert result["results"] == []

    @mock_aws
    @responses.activate
    def test_passes_patient_id_as_search_param(self):
        _bootstrap_aws()
        responses.get(
            f"{FHIR_BASE}/Encounter",
            json=_empty_bundle(),
            status=200,
        )
        handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "Encounter",
                "filters": {"status": "finished"},
            },
            None,
        )
        url = responses.calls[0].request.url
        assert f"patient={PATIENT_ID}" in url
        assert "status=finished" in url

    @mock_aws
    @responses.activate
    def test_enforces_count_cap(self):
        _bootstrap_aws()
        responses.get(
            f"{FHIR_BASE}/Observation",
            json=_empty_bundle(),
            status=200,
        )
        handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "Observation",
                "filters": {"_count": "50"},
            },
            None,
        )
        url = responses.calls[0].request.url
        assert "_count=10" in url


class TestAuditLogging:
    @mock_aws
    @responses.activate
    def test_writes_audit_record(self):
        _bootstrap_aws()
        responses.get(
            f"{FHIR_BASE}/DiagnosticReport",
            json=_bundle([{
                "resourceType": "DiagnosticReport",
                "id": "dr-audit",
                "status": "final",
            }]),
            status=200,
        )
        handler(
            {
                "practice_id": PRACTICE_ID,
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "DiagnosticReport",
            },
            None,
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        objects = s3.list_objects_v2(Bucket=AUDIT_BUCKET)
        assert objects["KeyCount"] >= 1


class TestCredentialErrors:
    @mock_aws
    def test_returns_credentials_expired(self):
        _bootstrap_aws()
        result = handler(
            {
                "practice_id": "nonexistent-practice",
                "call_id": CALL_ID,
                "patient_id": PATIENT_ID,
                "resource_type": "DiagnosticReport",
            },
            None,
        )
        assert result["status"] == "credentials_expired"
