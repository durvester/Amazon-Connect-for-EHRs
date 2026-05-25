"""OAuth onboarding routes (Session 0008).

Two routes in this module:

  GET /oauth/start
      Begin the SMART authorization-code flow for a practice. We do
      SMART discovery against the practice's FHIR base URL, mint a
      PKCE pair, write a one-time state row, then 302 the practice
      to the PF authorization endpoint.

  GET /oauth/callback
      Finish the flow. Consume the state row (single-use), exchange
      the code at the token endpoint (PKCE-verified), persist the
      practice's OAuth-adjacent config and KMS-encrypted tokens, claim
      a Connect DID, and write the phone_routing row that gives every
      future inbound call its tenant identifier.

Everything that talks to the network or AWS is provided via ``Deps``
so unit tests can substitute fakes and the Lambda runtime can pass
real implementations.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse


# ── DI surface ──────────────────────────────────────────────────────


class _StateStore(Protocol):
    def put(self, **kwargs) -> None: ...
    def get(self, state: str): ...
    def consume(self, state: str): ...


class _PracticesStore(Protocol):
    def put(self, **kwargs) -> None: ...


class _TokenStore(Protocol):
    def put(self, practice_id: str, access_token: str, refresh_token: str,
            *, expires_at: int) -> None: ...


class _PhoneRoutingStore(Protocol):
    def claim(self, phone_number: str, practice_id: str,
              connect_instance_id: str) -> None: ...


@dataclass
class OnboardingDeps:
    state_store: _StateStore
    practices_store: _PracticesStore
    token_store: _TokenStore
    phone_routing_store: _PhoneRoutingStore
    code_exchange: Callable          # exchange_authorization_code
    claim_did: Callable              # ConnectProvisioner.claim_did
    resolve_client_secret: Callable[[str], str]
    connect_instance_id: str
    redirect_uri: str
    # /oauth/start-only helpers (optional for callback-only tests).
    smart_discovery: Callable | None = None
    pkce_generate: Callable | None = None
    state_factory: Callable[[], str] | None = None
    state_ttl_seconds: int = 600


# ── Router ──────────────────────────────────────────────────────────


def build_router(deps: OnboardingDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/oauth/start")
    def start(practice_id: str, fhir_base_url: str,
              pf_client_id: str, pf_client_secret_arn: str) -> RedirectResponse:
        if deps.smart_discovery is None or deps.pkce_generate is None:
            # Runtime that wires /oauth/start always provides these; tests
            # that only exercise /oauth/callback may leave them None.
            raise HTTPException(status_code=500, detail="start route not configured")

        try:
            smart = deps.smart_discovery(fhir_base_url)
        except Exception as e:  # discovery surfaces SmartDiscoveryError
            raise HTTPException(
                status_code=502, detail=f"SMART discovery failed: {e}"
            ) from e

        pkce = deps.pkce_generate()
        state = (deps.state_factory or secrets.token_urlsafe)()
        if callable(state) is False and not isinstance(state, str):  # pragma: no cover
            state = str(state)

        deps.state_store.put(
            state=state,
            practice_id=practice_id,
            code_verifier=pkce.verifier,
            fhir_base_url=fhir_base_url,
            token_endpoint=smart.token_endpoint,
            pf_client_id=pf_client_id,
            pf_client_secret_arn=pf_client_secret_arn,
            ttl_seconds=deps.state_ttl_seconds,
        )

        params = {
            "response_type": "code",
            "client_id": pf_client_id,
            "redirect_uri": deps.redirect_uri,
            "scope": "openid fhirUser offline_access user/Patient.read "
                     "user/Observation.read user/DiagnosticReport.read "
                     "user/Encounter.read user/DocumentReference.read",
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": pkce.method,
            "aud": fhir_base_url,
        }
        return RedirectResponse(
            url=f"{smart.authorization_endpoint}?{urlencode(params)}",
            status_code=302,
        )

    @router.get("/oauth/callback")
    def callback(request: Request) -> dict:
        params = request.query_params
        state = params.get("state")
        code = params.get("code")
        error = params.get("error")
        if error:
            raise HTTPException(
                status_code=400, detail=f"authorization server returned error: {error}"
            )
        if not state or not code:
            raise HTTPException(status_code=400, detail="state and code are required")

        payload = deps.state_store.consume(state)
        if payload is None:
            raise HTTPException(
                status_code=400, detail="unknown or already-consumed state"
            )

        client_secret = deps.resolve_client_secret(payload.pf_client_secret_arn)

        token_set = deps.code_exchange(
            code=code,
            code_verifier=payload.code_verifier,
            token_endpoint=payload.token_endpoint,
            client_id=payload.pf_client_id,
            client_secret=client_secret,
            redirect_uri=deps.redirect_uri,
        )

        # ── Persist config + tokens BEFORE claiming a DID ────────────
        # If the DID claim throttles or fails, we still have the
        # tokens. A retry can finish the onboarding without a second
        # SMART round-trip — the state row is consumed, but the user
        # can re-run /oauth/start, get a fresh state, and the practice
        # row is already up-to-date.
        deps.practices_store.put(
            practice_id=payload.practice_id,
            fhir_base_url=payload.fhir_base_url,
            token_endpoint=payload.token_endpoint,
            pf_client_id=payload.pf_client_id,
            pf_client_secret_arn=payload.pf_client_secret_arn,
        )

        expires_at = int(time.time()) + int(token_set.expires_in or 0)
        deps.token_store.put(
            payload.practice_id,
            token_set.access_token,
            token_set.refresh_token,
            expires_at=expires_at,
        )

        did = deps.claim_did(connect_instance_id=deps.connect_instance_id)
        deps.phone_routing_store.claim(
            did, payload.practice_id, deps.connect_instance_id
        )

        return {
            "practice_id": payload.practice_id,
            "phone_number": did,
            "status": "onboarded",
        }

    return router
