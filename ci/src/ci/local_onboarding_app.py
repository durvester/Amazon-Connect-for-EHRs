"""Local FastAPI factory for the OAuth onboarding UI-E2E layer.

Wraps `api.app.build_app` with the surrounding state a Playwright spec
needs to drive the real PF QA SMART code-grant against a hermetic AWS
side:

  - moto mocks DynamoDB, KMS, and Secrets Manager (started in-process,
    shared with uvicorn — no separate moto server)
  - creates the four onboarding tables (oauth-state, practices,
    oauth-tokens, phone-routing) + an oauth-tokens KMS CMK + a fake PF
    client-secret in Secrets Manager
  - stubs ``ConnectProvisioner.claim_did`` to return a fixed DID so we
    don't spend ~$1 + burn an AWS Connect rate-limit slot per test run
  - exports env vars consumed by ``_build_default_deps_from_env`` so
    the onboarding routes get wired up

Run via:

    uvicorn ci.local_onboarding_app:build_app --factory --host 127.0.0.1 --port 8080

The redirect URI ``http://localhost:8080/oauth/callback`` is the
Veradigm-registered redirect for the PF QA Provider App
(see ``.env.example``), so port 8080 is not a free choice — PF's
redirect must match exactly.
"""

from __future__ import annotations

import os

from moto import mock_aws


_STUBBED_DID = os.environ.get("ONBOARDING_STUB_DID", "+15555550001")
_PF_CLIENT_SECRET_NAME = "pf-voice-local-pf-client-secret"
_MOCK = None  # outlives factory invocations; uvicorn warm reloads do not unbind


def _bootstrap_aws() -> dict[str, str]:
    """Start moto + create the resources the onboarding deps need.

    Returns the env-var dict that ``api.app._build_default_deps_from_env``
    expects. Idempotent — repeated calls return the same env (moto state
    persists within the process).
    """
    global _MOCK
    if _MOCK is None:
        _MOCK = mock_aws()
        _MOCK.start()

    import boto3

    region = os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    for k, v in (
        ("AWS_ACCESS_KEY_ID", "testing"),
        ("AWS_SECRET_ACCESS_KEY", "testing"),
        ("AWS_SESSION_TOKEN", "testing"),
    ):
        os.environ.setdefault(k, v)

    ddb = boto3.client("dynamodb", region_name=region)
    existing = set(ddb.list_tables()["TableNames"])
    for table, pk in [
        ("pf-voice-local-oauth-state", "state"),
        ("pf-voice-local-practices", "practice_id"),
        ("pf-voice-local-oauth-tokens", "practice_id"),
        ("pf-voice-local-phone-routing", "phone_number"),
    ]:
        if table in existing:
            continue
        ddb.create_table(
            TableName=table,
            KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

    kms = boto3.client("kms", region_name=region)
    key_id = kms.create_key(Description="local-onboarding-tokens")["KeyMetadata"]["KeyId"]

    sm = boto3.client("secretsmanager", region_name=region)
    try:
        secret = sm.create_secret(
            Name=_PF_CLIENT_SECRET_NAME,
            SecretString=os.environ.get("PF_CLIENT_SECRET", "fake-client-secret"),
        )
        secret_arn = secret["ARN"]
    except sm.exceptions.ResourceExistsException:
        secret_arn = sm.describe_secret(SecretId=_PF_CLIENT_SECRET_NAME)["ARN"]

    redirect_uri = os.environ.get(
        "PF_REDIRECT_URI", "http://localhost:8080/oauth/callback"
    )

    env = {
        "OAUTH_STATE_TABLE": "pf-voice-local-oauth-state",
        "PRACTICES_TABLE": "pf-voice-local-practices",
        "OAUTH_TOKENS_TABLE": "pf-voice-local-oauth-tokens",
        "OAUTH_TOKENS_KMS_KEY_ID": key_id,
        "PHONE_ROUTING_TABLE": "pf-voice-local-phone-routing",
        "CONNECT_INSTANCE_ID": "local-connect-instance",
        "CONNECT_INSTANCE_ARN": "arn:aws:connect:us-east-1:000000000000:instance/local",
        "OAUTH_REDIRECT_URI": redirect_uri,
        # Surfaced so the Playwright spec can read the same value via
        # /oauth/start params (we want the env, the spec, and PF to all
        # agree on the redirect URI).
        "LOCAL_PF_CLIENT_SECRET_ARN": secret_arn,
    }
    for k, v in env.items():
        os.environ[k] = v
    return env


def _install_connect_stub() -> None:
    """Replace ``ConnectProvisioner.claim_did`` with a fixed-DID stub.

    Done after env bootstrap so the production wiring path is exercised
    (we still go through ``api.app._build_default_deps_from_env`` and
    construct a real provisioner) — only the outbound AWS Connect call
    is intercepted.
    """
    from routing import connect_provisioner

    def _stub(self, *, connect_instance_id: str) -> str:  # noqa: ARG001
        return _STUBBED_DID

    connect_provisioner.ConnectProvisioner.claim_did = _stub  # type: ignore[assignment]


def build_app():
    _bootstrap_aws()
    _install_connect_stub()
    from api.app import build_app as _real_build_app
    return _real_build_app()
