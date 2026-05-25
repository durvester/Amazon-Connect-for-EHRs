"""FastAPI app factory.

Session 0005: stands up a minimal app with /healthz so the CI UI-E2E
harness can probe a real local stack.
Session 0008: adds the OAuth onboarding routes (/oauth/start +
/oauth/callback) via dependency-injected stores so unit tests can fake
the AWS + PF surface.

The Lambda entrypoint (Mangum) calls ``build_app()`` with no args.
``build_app(deps=...)`` is the test seam.
"""

from __future__ import annotations

from api.onboarding import OnboardingDeps


def build_app(deps: "OnboardingDeps | None" = None):
    from fastapi import FastAPI

    from api.routes.health import health

    app = FastAPI(title="pf-voice-api", version="0.0.1")
    app.get("/healthz")(health)

    if deps is None:
        deps = _build_default_deps_from_env()
    if deps is not None:
        from api.onboarding import build_router
        app.include_router(build_router(deps))

    return app


def _build_default_deps_from_env() -> "OnboardingDeps | None":
    """Construct production deps from env vars.

    Returns None when the env hasn't been wired (e.g. local healthz-only
    test stack from Session 0005). The healthz route still works in that
    mode; the onboarding routes are simply absent.
    """
    import os

    required = (
        "OAUTH_STATE_TABLE",
        "PRACTICES_TABLE",
        "OAUTH_TOKENS_TABLE",
        "OAUTH_TOKENS_KMS_KEY_ID",
        "PHONE_ROUTING_TABLE",
        "CONNECT_INSTANCE_ID",
        "CONNECT_INSTANCE_ARN",
        "OAUTH_REDIRECT_URI",
    )
    if any(not os.environ.get(k) for k in required):
        return None

    import boto3

    from oauth.client_secret_provider import resolve as resolve_client_secret
    from oauth.code_exchange import exchange_authorization_code
    from oauth.pkce import generate as pkce_generate
    from oauth.practices_store import PracticesStore
    from oauth.state_store import OAuthStateStore
    from oauth.token_store import TokenStore
    from oauth.well_known import fetch_smart_configuration
    from routing.connect_provisioner import ConnectProvisioner
    from routing.phone_routing_store import PhoneRoutingStore

    connect_client = boto3.client("connect")
    provisioner = ConnectProvisioner(
        connect_client=connect_client,
        instance_arn=os.environ["CONNECT_INSTANCE_ARN"],
    )

    return OnboardingDeps(
        state_store=OAuthStateStore(table_name=os.environ["OAUTH_STATE_TABLE"]),
        practices_store=PracticesStore(table_name=os.environ["PRACTICES_TABLE"]),
        token_store=TokenStore(
            table_name=os.environ["OAUTH_TOKENS_TABLE"],
            key_id=os.environ["OAUTH_TOKENS_KMS_KEY_ID"],
        ),
        phone_routing_store=PhoneRoutingStore(
            table_name=os.environ["PHONE_ROUTING_TABLE"],
        ),
        code_exchange=exchange_authorization_code,
        claim_did=provisioner.claim_did,
        resolve_client_secret=resolve_client_secret,
        connect_instance_id=os.environ["CONNECT_INSTANCE_ID"],
        redirect_uri=os.environ["OAUTH_REDIRECT_URI"],
        smart_discovery=fetch_smart_configuration,
        pkce_generate=pkce_generate,
    )


__all__ = ["build_app", "OnboardingDeps"]
