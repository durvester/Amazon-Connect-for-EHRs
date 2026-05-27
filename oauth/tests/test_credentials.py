"""Tests for the shared credential resolver (oauth.credentials)."""

from __future__ import annotations

import time

import boto3
import pytest
import responses
from moto import mock_aws

from oauth.credentials import CredentialsExpired, get_credentials
from oauth.practices_store import PracticesStore
from oauth.token_store import TokenStore

PRACTICE_ID = "pf-test-001"
FHIR_BASE = "https://qa-api.practicefusion.com/fhir/r4/v1/test-org"
TOKEN_ENDPOINT = "https://qa-api.practicefusion.com/oauth2/token"
CLIENT_ID = "test-client-id"
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789:secret:test-secret"

PRACTICES_TABLE = "practices-cred-test"
TOKENS_TABLE = "tokens-cred-test"
OAUTH_KEY_ALIAS = "alias/oauth-cred-test"


def _bootstrap_aws(*, expires_at: int = 9_999_999_999) -> tuple[PracticesStore, TokenStore]:
    kms = boto3.client("kms", region_name="us-east-1")
    cmk = kms.create_key(Description="oauth-test")["KeyMetadata"]["KeyId"]
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
    sm.create_secret(Name="test-secret", SecretString="client-secret-value")

    ps = PracticesStore(table_name=PRACTICES_TABLE, region="us-east-1")
    ps.put(
        practice_id=PRACTICE_ID,
        fhir_base_url=FHIR_BASE,
        token_endpoint=TOKEN_ENDPOINT,
        pf_client_id=CLIENT_ID,
        pf_client_secret_arn=SECRET_ARN,
    )

    ts = TokenStore(table_name=TOKENS_TABLE, key_id=OAUTH_KEY_ALIAS, region="us-east-1")
    ts.put(
        PRACTICE_ID,
        access_token="valid-access-token",
        refresh_token="valid-refresh-token",
        expires_at=expires_at,
    )

    return ps, ts


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("PRACTICES_TABLE_NAME", PRACTICES_TABLE)
    monkeypatch.setenv("TOKENS_TABLE_NAME", TOKENS_TABLE)
    monkeypatch.setenv("OAUTH_KMS_KEY_ARN", OAUTH_KEY_ALIAS)


class TestGetCredentials:
    @mock_aws
    def test_returns_fhir_base_url_and_token(self):
        ps, ts = _bootstrap_aws()
        base_url, token, refresh_ctx = get_credentials(
            PRACTICE_ID, practices_store=ps, token_store=ts
        )
        assert base_url == FHIR_BASE
        assert token == "valid-access-token"
        assert callable(refresh_ctx)

    @mock_aws
    def test_raises_when_no_practice_record(self):
        ps, ts = _bootstrap_aws()
        with pytest.raises(CredentialsExpired, match="no practices row"):
            get_credentials("nonexistent-practice", practices_store=ps, token_store=ts)

    @mock_aws
    def test_raises_when_no_token_record(self):
        ps, ts = _bootstrap_aws()
        ts._ddb.delete_item(
            TableName=TOKENS_TABLE,
            Key={"practice_id": {"S": PRACTICE_ID}},
        )
        with pytest.raises(CredentialsExpired, match="no active credentials"):
            get_credentials(PRACTICE_ID, practices_store=ps, token_store=ts)

    @mock_aws
    def test_raises_when_status_needs_reconnect(self):
        ps, ts = _bootstrap_aws()
        ts.mark_needs_reconnect(PRACTICE_ID)
        with pytest.raises(CredentialsExpired, match="needs_reconnect"):
            get_credentials(PRACTICE_ID, practices_store=ps, token_store=ts)


class TestTokenRefresh:
    @mock_aws
    @responses.activate
    def test_refreshes_near_expiry_token(self):
        ps, ts = _bootstrap_aws(expires_at=int(time.time()) + 30)

        responses.post(
            TOKEN_ENDPOINT,
            json={
                "access_token": "new-access-token",
                "refresh_token": "valid-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "user/Patient.read",
            },
            status=200,
        )

        base_url, token, refresh_ctx = get_credentials(
            PRACTICE_ID, practices_store=ps, token_store=ts
        )
        assert token == "new-access-token"

    @mock_aws
    @responses.activate
    def test_refresh_context_force_refreshes(self):
        ps, ts = _bootstrap_aws()

        responses.post(
            TOKEN_ENDPOINT,
            json={
                "access_token": "force-refreshed-token",
                "refresh_token": "valid-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "user/Patient.read",
            },
            status=200,
        )

        _, _, refresh_ctx = get_credentials(
            PRACTICE_ID, practices_store=ps, token_store=ts
        )
        new_token = refresh_ctx()
        assert new_token == "force-refreshed-token"

    @mock_aws
    @responses.activate
    def test_invalid_grant_raises_credentials_expired(self):
        ps, ts = _bootstrap_aws(expires_at=int(time.time()) + 30)

        responses.post(
            TOKEN_ENDPOINT,
            json={"error": "invalid_grant", "error_description": "token revoked"},
            status=400,
        )

        with pytest.raises(CredentialsExpired, match="refresh failed"):
            get_credentials(PRACTICE_ID, practices_store=ps, token_store=ts)

        record = ts.get(PRACTICE_ID)
        assert record.status == "needs_reconnect"
