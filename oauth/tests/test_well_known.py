"""Tests for SMART discovery via /.well-known/smart-configuration."""

from unittest.mock import patch

import pytest

from oauth.well_known import (
    SmartConfiguration,
    SmartDiscoveryError,
    fetch_smart_configuration,
)

# Real PF QA response shape, captured 2026-05-23 from
# https://qa-api.practicefusion.com/fhir/r4/v1/{org-uuid}/.well-known/smart-configuration
_PF_QA_RESPONSE = {
    "issuer": "https://qa-api.practicefusion.com/fhir/r4/v1/uuid",
    "jwks_uri": "https://qa-api.practicefusion.com/fhir/r4/v1/uuid/.well-known/jwk",
    "authorization_endpoint": "https://qa-api.practicefusion.com/fhir/r4/v1/uuid/authorize",
    "token_endpoint": "https://qa-api.practicefusion.com/fhir/r4/v1/uuid/token",
    "introspection_endpoint": "https://qa-api.practicefusion.com/fhir/r4/v1/uuid/introspect",
    "capabilities": [
        "launch-standalone",
        "client-confidential-symmetric",
        "permission-offline",
        "permission-user",
    ],
    "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
    "code_challenge_methods_supported": ["S256"],
}


class _MockResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_parses_pf_qa_response_shape():
    with patch("oauth.well_known.requests.get", return_value=_MockResponse(200, _PF_QA_RESPONSE)) as g:
        cfg = fetch_smart_configuration("https://qa-api.practicefusion.com/fhir/r4/v1/uuid")
    assert isinstance(cfg, SmartConfiguration)
    assert cfg.authorization_endpoint == _PF_QA_RESPONSE["authorization_endpoint"]
    assert cfg.token_endpoint == _PF_QA_RESPONSE["token_endpoint"]
    assert cfg.issuer == _PF_QA_RESPONSE["issuer"]
    assert "S256" in cfg.code_challenge_methods_supported
    # Tolerates the discovery URL with or without trailing slash.
    g.assert_called_once()
    url = g.call_args[0][0]
    assert url.endswith("/.well-known/smart-configuration")


def test_supports_pkce_helper():
    cfg = SmartConfiguration(
        issuer="i",
        authorization_endpoint="a",
        token_endpoint="t",
        jwks_uri="j",
        capabilities=[],
        grant_types_supported=["authorization_code"],
        code_challenge_methods_supported=["S256"],
    )
    assert cfg.supports_pkce_s256() is True

    cfg_no_pkce = SmartConfiguration(
        issuer="i",
        authorization_endpoint="a",
        token_endpoint="t",
        jwks_uri="j",
        capabilities=[],
        grant_types_supported=["authorization_code"],
        code_challenge_methods_supported=[],
    )
    assert cfg_no_pkce.supports_pkce_s256() is False


def test_supports_capability_helper():
    cfg = SmartConfiguration(
        issuer="i",
        authorization_endpoint="a",
        token_endpoint="t",
        jwks_uri="j",
        capabilities=["launch-standalone", "permission-offline"],
        grant_types_supported=[],
        code_challenge_methods_supported=[],
    )
    assert cfg.has_capability("launch-standalone") is True
    assert cfg.has_capability("launch-ehr") is False


def test_missing_required_field_raises():
    bad = dict(_PF_QA_RESPONSE)
    del bad["authorization_endpoint"]
    with patch("oauth.well_known.requests.get", return_value=_MockResponse(200, bad)):
        with pytest.raises(SmartDiscoveryError):
            fetch_smart_configuration("https://x/")


def test_http_error_raises():
    with patch("oauth.well_known.requests.get", return_value=_MockResponse(500, {})):
        with pytest.raises(SmartDiscoveryError):
            fetch_smart_configuration("https://x/")


def test_strips_trailing_slash_on_base_url():
    with patch("oauth.well_known.requests.get", return_value=_MockResponse(200, _PF_QA_RESPONSE)) as g:
        fetch_smart_configuration("https://x/")
    url = g.call_args[0][0]
    # Exactly one /.well-known/... regardless of trailing slash on input.
    assert url == "https://x/.well-known/smart-configuration"
