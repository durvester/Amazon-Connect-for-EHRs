"""Tests for the /oauth/start route (Session 0008).

The route does SMART discovery, mints a PKCE pair, persists a state
row, and redirects to the authorization endpoint. We verify the
redirect URL carries the right query parameters and that the
persisted state captures the PKCE verifier + practice metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("moto")


PRACTICE_ID = "pf-start-001"
FHIR_BASE_URL = "https://qa-api.practicefusion.com/fhir/r4/v1/org-x"
AUTH_ENDPOINT = "https://qa-auth.practicefusion.com/oauth/v1/authorize"
TOKEN_ENDPOINT = "https://qa-auth.practicefusion.com/oauth/v1/token"
PF_CLIENT_ID = "cid"
PF_CLIENT_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:0:secret:x"
REDIRECT_URI = "https://onboarding.example.com/oauth/callback"
INSTANCE_ID = "11111111-2222-3333-4444-555555555555"


@dataclass
class _FakeSmart:
    authorization_endpoint: str
    token_endpoint: str
    issuer: str = "irrelevant"
    jwks_uri: str = "irrelevant"


@dataclass
class _FakePkce:
    verifier: str
    challenge: str
    method: str = "S256"


def _setup():
    import boto3
    from moto import mock_aws
    ctx = mock_aws()
    ctx.start()

    boto3.client("dynamodb", region_name="us-east-1").create_table(
        TableName="oauth-state-test",
        KeySchema=[{"AttributeName": "state", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "state", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    from api.app import OnboardingDeps, build_app
    from oauth.state_store import OAuthStateStore

    deps = OnboardingDeps(
        state_store=OAuthStateStore(table_name="oauth-state-test"),
        practices_store=None,
        token_store=None,
        phone_routing_store=None,
        code_exchange=lambda **_: None,
        claim_did=lambda **_: None,
        resolve_client_secret=lambda _: None,
        connect_instance_id=INSTANCE_ID,
        redirect_uri=REDIRECT_URI,
        smart_discovery=lambda url: _FakeSmart(
            authorization_endpoint=AUTH_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
        ),
        pkce_generate=lambda: _FakePkce(verifier="v" * 64, challenge="ch-XYZ"),
        state_factory=lambda: "fixed-state-abc",
    )
    return TestClient(build_app(deps=deps)), deps, ctx


def _envset(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
              "AWS_DEFAULT_REGION"):
        monkeypatch.setenv(k, "testing" if "REGION" not in k else "us-east-1")


def test_start_redirects_with_pkce_and_state(monkeypatch):
    _envset(monkeypatch)
    client, deps, ctx = _setup()
    try:
        r = client.get(
            "/oauth/start",
            params={
                "practice_id": PRACTICE_ID,
                "fhir_base_url": FHIR_BASE_URL,
                "pf_client_id": PF_CLIENT_ID,
                "pf_client_secret_arn": PF_CLIENT_SECRET_ARN,
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith(AUTH_ENDPOINT + "?")
        assert "response_type=code" in loc
        assert "code_challenge=ch-XYZ" in loc
        assert "code_challenge_method=S256" in loc
        assert "state=fixed-state-abc" in loc
        assert "client_id=cid" in loc

        # State row persisted with the PKCE verifier for the callback to use.
        payload = deps.state_store.get("fixed-state-abc")
        assert payload is not None
        assert payload.practice_id == PRACTICE_ID
        assert payload.code_verifier == "v" * 64
        assert payload.token_endpoint == TOKEN_ENDPOINT
        assert payload.fhir_base_url == FHIR_BASE_URL
    finally:
        ctx.stop()
