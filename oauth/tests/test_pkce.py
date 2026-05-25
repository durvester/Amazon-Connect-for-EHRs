"""Tests for the PKCE generator. RFC 7636 conformance."""

import base64
import hashlib

import pytest

from oauth.pkce import PkceError, challenge_for, generate


def test_generates_default_pair():
    pair = generate()
    assert pair.method == "S256"
    assert 43 <= len(pair.verifier) <= 128
    # challenge is the SHA-256 of the verifier, base64url, no padding
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(pair.verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert pair.challenge == expected


def test_each_call_is_unique():
    a = generate()
    b = generate()
    assert a.verifier != b.verifier
    assert a.challenge != b.challenge


@pytest.mark.parametrize("n", [31, 0, 97, 200])
def test_rejects_out_of_range_entropy(n):
    with pytest.raises(PkceError):
        generate(verifier_bytes=n)


def test_challenge_for_validates_length():
    with pytest.raises(PkceError):
        challenge_for("too-short")
    with pytest.raises(PkceError):
        challenge_for("x" * 129)


def test_challenge_is_deterministic():
    # Known verifier → known challenge, per RFC 7636 §A example
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(v) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
