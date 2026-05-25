"""Tests for the SMART-on-FHIR refresh-token exchange.

HTTP is mocked with `responses`; the integration counterpart lives in
`test_integration_refresh.py` and is skipped unless `PF_REFRESH_TOKEN` is set.
"""

from __future__ import annotations

import pytest
import responses

from oauth.refresh import (
    InvalidGrantError,
    RefreshTokenError,
    TokenSet,
    refresh_access_token,
)

TOKEN_ENDPOINT = "https://qa-auth.practicefusion.com/oauth/v1/token"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
REFRESH = "old-refresh-token"


def _token_response(**overrides):
    body = {
        "access_token": "new-access-token",
        "token_type": "Bearer",
        "expires_in": 300,
        "scope": "user/Patient.read offline_access fhirUser",
    }
    body.update(overrides)
    return body


@responses.activate
def test_refreshes_access_token_against_mocked_pf():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json=_token_response(refresh_token="new-refresh-token"),
        status=200,
    )

    result = refresh_access_token(
        refresh_token=REFRESH,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    assert isinstance(result, TokenSet)
    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"
    assert result.expires_in == 300
    assert result.token_type == "Bearer"
    assert "user/Patient.read" in result.scope


@responses.activate
def test_sends_refresh_token_grant_with_client_secret_post():
    responses.add(responses.POST, TOKEN_ENDPOINT, json=_token_response(), status=200)

    refresh_access_token(
        refresh_token=REFRESH,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    body = responses.calls[0].request.body
    # body is form-encoded; parse loosely
    parsed = dict(pair.split("=", 1) for pair in body.split("&"))
    assert parsed["grant_type"] == "refresh_token"
    assert parsed["refresh_token"] == REFRESH
    assert parsed["client_id"] == CLIENT_ID
    assert parsed["client_secret"] == CLIENT_SECRET


@responses.activate
def test_omitted_refresh_in_response_reuses_input_refresh_token():
    # PF may or may not rotate. If the response omits refresh_token, we keep
    # using the one we sent in. Test asserts this non-rotating path.
    responses.add(responses.POST, TOKEN_ENDPOINT, json=_token_response(), status=200)

    result = refresh_access_token(
        refresh_token=REFRESH,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    assert result.refresh_token == REFRESH


@responses.activate
def test_rotated_refresh_in_response_supersedes_input():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json=_token_response(refresh_token="rotated"),
        status=200,
    )
    result = refresh_access_token(
        refresh_token=REFRESH,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    assert result.refresh_token == "rotated"


@responses.activate
def test_400_invalid_grant_raises():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_grant"},
        status=400,
    )
    with pytest.raises(RefreshTokenError) as exc_info:
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
    assert "invalid_grant" in str(exc_info.value)


@responses.activate
def test_401_invalid_client_raises():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_client"},
        status=401,
    )
    with pytest.raises(RefreshTokenError):
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )


@responses.activate
def test_500_raises():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        body="internal server error",
        status=500,
    )
    with pytest.raises(RefreshTokenError):
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )


@responses.activate
def test_response_missing_access_token_raises():
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"token_type": "Bearer", "expires_in": 300},
        status=200,
    )
    with pytest.raises(RefreshTokenError):
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )


@pytest.mark.parametrize("missing", ["refresh_token", "token_endpoint", "client_id"])
def test_rejects_empty_required_args(missing):
    args = {
        "refresh_token": REFRESH,
        "token_endpoint": TOKEN_ENDPOINT,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    args[missing] = ""
    with pytest.raises(RefreshTokenError):
        refresh_access_token(**args)


@responses.activate
def test_invalid_grant_raises_invalid_grant_error():
    """400 + body {'error': 'invalid_grant'} → InvalidGrantError (a subclass
    of RefreshTokenError, so existing handlers still catch it broadly).
    """
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_grant", "error_description": "Refresh token revoked"},
        status=400,
    )
    with pytest.raises(InvalidGrantError):
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )


@responses.activate
def test_other_400_does_not_raise_invalid_grant_error():
    """A 400 without 'invalid_grant' stays a plain RefreshTokenError —
    callers should not mark_needs_reconnect on every 400.
    """
    responses.add(
        responses.POST,
        TOKEN_ENDPOINT,
        json={"error": "invalid_request", "error_description": "bad params"},
        status=400,
    )
    with pytest.raises(RefreshTokenError) as exc:
        refresh_access_token(
            refresh_token=REFRESH,
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
    assert not isinstance(exc.value, InvalidGrantError)
