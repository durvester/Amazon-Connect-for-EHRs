"""SMART-on-FHIR refresh-token exchange against a token endpoint.

Uses `client_secret_post` (credentials in the request body) — empirically
accepted by Practice Fusion (Session 0002 finding). The function is HTTP-only;
storage and rotation are the token_store module's job.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

_TIMEOUT_SECONDS = 10.0


class RefreshTokenError(RuntimeError):
    """Raised on any non-2xx response, missing/malformed body, or bad input."""


class InvalidGrantError(RefreshTokenError):
    """The stored refresh token is no longer valid at the token endpoint.

    Distinct from the broader ``RefreshTokenError`` because callers must
    treat it specially: the only recovery is to ``mark_needs_reconnect``
    on the practice and route the call to a human while the provider
    re-authorizes. Retrying with the same refresh token will keep
    failing the same way.

    Standard OAuth 2.0 ``invalid_grant`` is the spec-defined signal for
    this; PF returns it on revoked / expired / consumed refresh tokens.
    """


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    scope: str


def refresh_access_token(
    *,
    refresh_token: str,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
) -> TokenSet:
    """Exchange a refresh token for a new access token.

    If the server omits `refresh_token` from the response (non-rotating
    server), the input `refresh_token` is preserved on the returned
    TokenSet so callers can persist a stable value.
    """
    if not refresh_token or not token_endpoint or not client_id:
        raise RefreshTokenError(
            "refresh_token, token_endpoint, and client_id are required"
        )

    try:
        resp = requests.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise RefreshTokenError(f"token endpoint unreachable: {e}") from e

    if not resp.ok:
        snippet = resp.text[:200] if resp.text else ""
        # OAuth 2.0 §5.2: 400 + body {"error": "invalid_grant", ...} means
        # the refresh token is no longer accepted. Surface that as a
        # dedicated error so callers can mark_needs_reconnect.
        if resp.status_code == 400:
            try:
                err = (resp.json() or {}).get("error")
            except ValueError:
                err = None
            if err == "invalid_grant":
                raise InvalidGrantError(
                    f"refresh token rejected by token endpoint: {snippet}"
                )
        raise RefreshTokenError(
            f"token endpoint returned {resp.status_code}: {snippet}"
        )

    try:
        body = resp.json()
    except ValueError as e:
        raise RefreshTokenError(f"non-JSON response: {resp.text[:200]}") from e

    access = body.get("access_token")
    if not access:
        raise RefreshTokenError(f"response missing access_token: {body}")

    return TokenSet(
        access_token=access,
        refresh_token=body.get("refresh_token") or refresh_token,
        expires_in=int(body.get("expires_in", 0)),
        token_type=body.get("token_type", "Bearer"),
        scope=body.get("scope", ""),
    )
