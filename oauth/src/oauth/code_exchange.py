"""SMART-on-FHIR authorization_code → token exchange (Session 0008).

Runs once per practice, on /oauth/callback. After a successful exchange
the caller persists the resulting TokenSet via `token_store.put` and the
practice's OAuth-adjacent config via `practices_store.put`.

PKCE is mandatory — the `code_verifier` is the half of the pair that
never leaves us until this exact call. PF accepts `client_secret_post`
(credentials in the body); same auth style as the refresh exchange.
"""

from __future__ import annotations

import requests

from oauth.refresh import TokenSet

_TIMEOUT_SECONDS = 10.0


class AuthCodeExchangeError(RuntimeError):
    """Raised on any non-2xx response, missing/malformed body, or bad input."""


def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> TokenSet:
    """Exchange a SMART authorization code for an access + refresh token pair."""
    for label, value in (
        ("code", code),
        ("code_verifier", code_verifier),
        ("token_endpoint", token_endpoint),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
    ):
        if not value:
            raise AuthCodeExchangeError(f"{label} is required")

    try:
        resp = requests.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise AuthCodeExchangeError(f"token endpoint unreachable: {e}") from e

    if not resp.ok:
        snippet = resp.text[:200] if resp.text else ""
        raise AuthCodeExchangeError(
            f"token endpoint returned {resp.status_code}: {snippet}"
        )

    try:
        body = resp.json()
    except ValueError as e:
        raise AuthCodeExchangeError(f"non-JSON response: {resp.text[:200]}") from e

    access = body.get("access_token")
    refresh = body.get("refresh_token")
    if not access:
        raise AuthCodeExchangeError(f"response missing access_token: {body}")
    if not refresh:
        # The auth-code flow MUST yield a refresh_token (SMART offline_access
        # scope). Without it the practice would be un-refreshable and the
        # whole onboarding is wasted. Refuse to persist.
        raise AuthCodeExchangeError(
            "response missing refresh_token — offline_access scope may not "
            "have been granted"
        )

    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(body.get("expires_in", 0)),
        token_type=body.get("token_type", "Bearer"),
        scope=body.get("scope", ""),
    )
