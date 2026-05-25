"""SMART-on-FHIR discovery via /.well-known/smart-configuration.

Reference: https://www.hl7.org/fhir/smart-app-launch/conformance.html#using-well-known
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


_DISCOVERY_PATH = "/.well-known/smart-configuration"
_REQUIRED_FIELDS = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
)


class SmartDiscoveryError(RuntimeError):
    """Raised when SMART discovery cannot be completed or parsed."""


@dataclass(frozen=True)
class SmartConfiguration:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    capabilities: list[str] = field(default_factory=list)
    grant_types_supported: list[str] = field(default_factory=list)
    code_challenge_methods_supported: list[str] = field(default_factory=list)
    introspection_endpoint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def supports_pkce_s256(self) -> bool:
        return "S256" in self.code_challenge_methods_supported

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


def fetch_smart_configuration(fhir_base_url: str, *, timeout: float = 5.0) -> SmartConfiguration:
    """Fetch and parse the SMART configuration for a FHIR base URL.

    Returns a ``SmartConfiguration``. Raises ``SmartDiscoveryError`` on HTTP
    failure, JSON-parse failure, or missing required fields.
    """
    url = fhir_base_url.rstrip("/") + _DISCOVERY_PATH
    try:
        response = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
        response.raise_for_status()
    except Exception as exc:
        raise SmartDiscoveryError(f"discovery GET failed: {url} ({exc})") from exc

    try:
        body = response.json()
    except Exception as exc:
        raise SmartDiscoveryError(f"discovery response was not JSON: {url}") from exc

    missing = [f for f in _REQUIRED_FIELDS if f not in body]
    if missing:
        raise SmartDiscoveryError(f"discovery response missing required fields: {missing}")

    return SmartConfiguration(
        issuer=body["issuer"],
        authorization_endpoint=body["authorization_endpoint"],
        token_endpoint=body["token_endpoint"],
        jwks_uri=body["jwks_uri"],
        capabilities=list(body.get("capabilities", [])),
        grant_types_supported=list(body.get("grant_types_supported", [])),
        code_challenge_methods_supported=list(body.get("code_challenge_methods_supported", [])),
        introspection_endpoint=body.get("introspection_endpoint"),
        raw=body,
    )
