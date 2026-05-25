"""Tests for the SMART authorization_code → access_token exchange.

Mirrors test_refresh.py's structure. The real HTTP call is mocked via
`responses`; the integration counterpart will live behind a PF_* gate
once we have a real auth code to play back.
"""

from __future__ import annotations

import pytest
import responses

from oauth.code_exchange import (
    AuthCodeExchangeError,
    exchange_authorization_code,
)
from oauth.refresh import TokenSet

TOKEN_ENDPOINT = "https://qa-auth.practicefusion.com/oauth/v1/token"
CLIENT_ID = "pf-client-id"
CLIENT_SECRET = "pf-client-secret"
REDIRECT_URI = "https://onboarding.example.com/oauth/callback"
CODE = "auth-code-123"
VERIFIER = "v" * 64


def _body(**overrides):
    body = {
        "access_token": "access-XYZ",
        "refresh_token": "refresh-XYZ",
        "token_type": "Bearer",
        "expires_in": 300,
        "scope": "user/Patient.read offline_access fhirUser",
    }
    body.update(overrides)
    return body


@responses.activate
def test_exchanges_code_for_token_set():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json=_body(),
        status=200,
    )
    out = exchange_authorization_code(
        code=CODE,
        code_verifier=VERIFIER,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )
    assert isinstance(out, TokenSet)
    assert out.access_token == "access-XYZ"
    assert out.refresh_token == "refresh-XYZ"
    assert out.expires_in == 300

    # Posted form fields are right.
    sent = responses.calls[0].request.body
    assert "grant_type=authorization_code" in sent
    assert f"code={CODE}" in sent
    assert f"code_verifier={VERIFIER}" in sent
    assert "client_id=pf-client-id" in sent


@responses.activate
def test_raises_on_non_2xx():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_grant"},
        status=400,
    )
    with pytest.raises(AuthCodeExchangeError):
        exchange_authorization_code(
            code=CODE,
            code_verifier=VERIFIER,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
        )


@responses.activate
def test_raises_when_access_token_missing():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"token_type": "Bearer", "expires_in": 300},
        status=200,
    )
    with pytest.raises(AuthCodeExchangeError):
        exchange_authorization_code(
            code=CODE,
            code_verifier=VERIFIER,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
        )


def test_requires_all_inputs():
    with pytest.raises(AuthCodeExchangeError):
        exchange_authorization_code(
            code="",
            code_verifier=VERIFIER,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
        )
