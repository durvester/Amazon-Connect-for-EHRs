"""End-to-end test for the OAuth onboarding callback (Session 0008).

Drives the FastAPI `/oauth/callback` route through dependency-injected
fakes. Asserts that on a successful PF authorization-code exchange the
callback writes the practices row, the encrypted token row, claims a
Connect DID, and writes the phone_routing row — the full multi-tenancy
chain coming into existence in one atomic-ish API call.

The state store, practices store, token store, and phone_routing store
are real moto-backed implementations (we want to exercise the actual
DDB serialization paths). The PF token endpoint, the Connect DID claim,
and the Secrets Manager fetch are stubbed via injected callables so the
test is hermetic.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient


pytest.importorskip("moto", reason="moto required for onboarding callback tests")
pytest.importorskip("boto3", reason="boto3 required for onboarding callback tests")


PRACTICE_ID = "pf-test-001"
FHIR_BASE_URL = "https://qa-api.practicefusion.com/fhir/r4/v1/org-x"
TOKEN_ENDPOINT = "https://qa-auth.practicefusion.com/oauth/v1/token"
PF_CLIENT_ID = "pf-client-id-test"
PF_CLIENT_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:0:secret:pf-client-secret-AbCdEf"
CONNECT_INSTANCE_ID = "11111111-2222-3333-4444-555555555555"
REDIRECT_URI = "https://onboarding.example.com/oauth/callback"
STATE = "state-abc"
CODE_VERIFIER = "v" * 64
AUTH_CODE = "auth-code-from-pf"
CLAIMED_DID = "+15551234567"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@dataclass
class _Probe:
    """Capture spies for the stubbed callables so we can assert call shape."""
    exchange_calls: list[dict]
    claim_calls: list[dict]
    secret_calls: list[str]


def _build_client(aws_env):
    """Spin up moto-mocked DDB + KMS, build the FastAPI app with injected deps."""
    import boto3
    from moto import mock_aws

    mock_ctx = mock_aws()
    mock_ctx.start()

    # ── KMS CMK for the token store ──────────────────────────────────
    kms = boto3.client("kms", region_name="us-east-1")
    key_id = kms.create_key(Description="onboarding-test")["KeyMetadata"]["KeyId"]

    # ── DDB tables (oauth-state, practices, oauth-tokens, phone-routing) ─
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    for table, pk in [
        ("oauth-state-test", "state"),
        ("practices-test", "practice_id"),
        ("oauth-tokens-test", "practice_id"),
        ("phone-routing-test", "phone_number"),
    ]:
        ddb.create_table(
            TableName=table,
            KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

    # ── Real stores ──────────────────────────────────────────────────
    from oauth.state_store import OAuthStateStore
    from oauth.practices_store import PracticesStore
    from oauth.token_store import TokenStore
    from routing.phone_routing_store import PhoneRoutingStore

    state_store = OAuthStateStore(table_name="oauth-state-test")
    practices_store = PracticesStore(table_name="practices-test")
    token_store = TokenStore(table_name="oauth-tokens-test", key_id=key_id)
    phone_routing = PhoneRoutingStore(table_name="phone-routing-test")

    # Pre-seed the state row as if /oauth/start had run.
    state_store.put(
        state=STATE,
        practice_id=PRACTICE_ID,
        code_verifier=CODE_VERIFIER,
        fhir_base_url=FHIR_BASE_URL,
        token_endpoint=TOKEN_ENDPOINT,
        pf_client_id=PF_CLIENT_ID,
        pf_client_secret_arn=PF_CLIENT_SECRET_ARN,
        ttl_seconds=600,
    )

    probe = _Probe(exchange_calls=[], claim_calls=[], secret_calls=[])

    def fake_exchange(**kwargs):
        from oauth.refresh import TokenSet
        probe.exchange_calls.append(kwargs)
        return TokenSet(
            access_token="access-XYZ",
            refresh_token="refresh-XYZ",
            expires_in=300,
            token_type="Bearer",
            scope="user/Patient.read offline_access fhirUser",
        )

    def fake_claim_did(*, connect_instance_id):
        probe.claim_calls.append({"connect_instance_id": connect_instance_id})
        return CLAIMED_DID

    def fake_resolve_secret(arn):
        probe.secret_calls.append(arn)
        return "pf-client-secret-plaintext"

    from api.app import OnboardingDeps, build_app

    deps = OnboardingDeps(
        state_store=state_store,
        practices_store=practices_store,
        token_store=token_store,
        phone_routing_store=phone_routing,
        code_exchange=fake_exchange,
        claim_did=fake_claim_did,
        resolve_client_secret=fake_resolve_secret,
        connect_instance_id=CONNECT_INSTANCE_ID,
        redirect_uri=REDIRECT_URI,
    )

    app = build_app(deps=deps)
    client = TestClient(app)
    return client, deps, probe, mock_ctx


def test_callback_claims_did_and_writes_phone_routing(aws_env):
    client, deps, probe, mock_ctx = _build_client(aws_env)
    try:
        r = client.get(f"/oauth/callback?state={STATE}&code={AUTH_CODE}")

        # ── Response shape ───────────────────────────────────────────
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["practice_id"] == PRACTICE_ID
        assert body["phone_number"] == CLAIMED_DID
        assert body["status"] == "onboarded"

        # ── PF code exchange got the right inputs ────────────────────
        assert len(probe.exchange_calls) == 1
        call = probe.exchange_calls[0]
        assert call["code"] == AUTH_CODE
        assert call["code_verifier"] == CODE_VERIFIER
        assert call["token_endpoint"] == TOKEN_ENDPOINT
        assert call["client_id"] == PF_CLIENT_ID
        assert call["client_secret"] == "pf-client-secret-plaintext"
        assert call["redirect_uri"] == REDIRECT_URI

        # Secrets Manager resolved exactly the configured ARN
        assert probe.secret_calls == [PF_CLIENT_SECRET_ARN]

        # Connect DID claim against the configured instance
        assert probe.claim_calls == [{"connect_instance_id": CONNECT_INSTANCE_ID}]

        # ── practices row written with the OAuth-adjacent config ─────
        practice = deps.practices_store.get(PRACTICE_ID)
        assert practice.fhir_base_url == FHIR_BASE_URL
        assert practice.token_endpoint == TOKEN_ENDPOINT
        assert practice.pf_client_id == PF_CLIENT_ID
        assert practice.pf_client_secret_arn == PF_CLIENT_SECRET_ARN

        # ── encrypted token row written ──────────────────────────────
        token = deps.token_store.get(PRACTICE_ID)
        assert token is not None
        assert token.access_token == "access-XYZ"
        assert token.refresh_token == "refresh-XYZ"
        assert token.status == "active"
        assert token.expires_at > 0  # rounded from now + expires_in

        # ── phone_routing row written: DID → practice_id ─────────────
        assert deps.phone_routing_store.resolve(CLAIMED_DID) == PRACTICE_ID
        rec = deps.phone_routing_store.get_record(CLAIMED_DID)
        assert rec.connect_instance_id == CONNECT_INSTANCE_ID
        assert rec.status == "active"

        # ── state row consumed (single-use) ──────────────────────────
        assert deps.state_store.get(STATE) is None
    finally:
        mock_ctx.stop()


def test_callback_rejects_unknown_state(aws_env):
    client, _deps, _probe, mock_ctx = _build_client(aws_env)
    try:
        r = client.get("/oauth/callback?state=does-not-exist&code=irrelevant")
        assert r.status_code == 400
        assert "state" in r.json()["detail"].lower()
    finally:
        mock_ctx.stop()


def test_callback_is_idempotent_on_replay(aws_env):
    """Re-running the callback with the same state must not double-claim
    a DID or rewrite tokens. Session 0008 enforces single-use state."""
    client, _deps, probe, mock_ctx = _build_client(aws_env)
    try:
        first = client.get(f"/oauth/callback?state={STATE}&code={AUTH_CODE}")
        assert first.status_code == 200

        second = client.get(f"/oauth/callback?state={STATE}&code={AUTH_CODE}")
        assert second.status_code == 400  # state already consumed
        assert len(probe.claim_calls) == 1  # no second DID claimed
        assert len(probe.exchange_calls) == 1  # no second token exchange
    finally:
        mock_ctx.stop()
