"""PKCE — Proof Key for Code Exchange (RFC 7636).

Generates a `code_verifier` (random) and the `code_challenge` (base64url-encoded
SHA-256 of the verifier). Used in the SMART-on-FHIR `authorization_code` flow
to bind the auth request to the eventual code exchange so an intercepted code
cannot be redeemed by anyone but the original requester.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass


# RFC 7636 §4.1: verifier must be 43..128 chars from the unreserved alphabet.
_MIN_VERIFIER_BYTES = 32  # 32 random bytes -> 43-char base64url
_MAX_VERIFIER_BYTES = 96  # 96 random bytes -> 128-char base64url


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str
    method: str = "S256"


class PkceError(ValueError):
    """Raised when verifier inputs are out of spec."""


def generate(verifier_bytes: int = 32) -> PkcePair:
    """Generate a fresh PKCE pair using SHA-256.

    `verifier_bytes` controls entropy — 32 (default) yields a 43-char verifier,
    which is RFC 7636's minimum length.
    """
    if not _MIN_VERIFIER_BYTES <= verifier_bytes <= _MAX_VERIFIER_BYTES:
        raise PkceError(
            f"verifier_bytes must be in [{_MIN_VERIFIER_BYTES}, {_MAX_VERIFIER_BYTES}]"
        )
    verifier = _b64url(secrets.token_bytes(verifier_bytes))
    challenge = challenge_for(verifier)
    return PkcePair(verifier=verifier, challenge=challenge, method="S256")


def challenge_for(verifier: str) -> str:
    """Compute the S256 code_challenge for a given verifier."""
    if not 43 <= len(verifier) <= 128:
        raise PkceError("verifier length must be 43..128 chars (RFC 7636 §4.1)")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")
