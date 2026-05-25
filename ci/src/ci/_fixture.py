"""Shared helpers for the sealed-box-encrypted dev refresh-token fixture.

QA-only. Production uses AWS Secrets Manager (see docs/architecture.md).

Layout on disk:
  secrets/pf-qa-refresh-token.enc  — sealed-box ciphertext over the JSON
                                     blob {refresh_token, client_id,
                                     client_secret, fhir_base_url}
  secrets/dev-fixture-pubkey.b64   — base64 public key (checked in;
                                     anyone can re-encrypt the fixture)

The private key lives in the env var PF_DEV_FIXTURE_PRIVKEY (base64).
Locally that's a developer's keypair; in GitHub Actions it's a repo
secret. Sealed-box gives "anyone can encrypt with the public key; only
the private key can decrypt" — the property we want for a checked-in
ciphertext.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CIPHERTEXT_PATH = REPO_ROOT / "secrets" / "pf-qa-refresh-token.enc"
PUBKEY_PATH = REPO_ROOT / "secrets" / "dev-fixture-pubkey.b64"
PRIVKEY_ENV = "PF_DEV_FIXTURE_PRIVKEY"


class FixtureUnavailable(RuntimeError):
    """Ciphertext missing, private key missing, or decryption failed."""


@dataclass(frozen=True)
class DevTokenBundle:
    refresh_token: str
    client_id: str
    client_secret: str
    fhir_base_url: str


def load_pubkey() -> bytes:
    if not PUBKEY_PATH.exists():
        raise FixtureUnavailable(
            f"public key not found at {PUBKEY_PATH}; run `make seed-dev-token` "
            "to generate a keypair first"
        )
    return base64.b64decode(PUBKEY_PATH.read_text().strip())


def decrypt_bundle() -> DevTokenBundle:
    if not CIPHERTEXT_PATH.exists():
        raise FixtureUnavailable(f"ciphertext not found at {CIPHERTEXT_PATH}")

    privkey_b64 = os.environ.get(PRIVKEY_ENV)
    if not privkey_b64:
        raise FixtureUnavailable(f"env var {PRIVKEY_ENV} not set")

    try:
        from nacl.public import PrivateKey, SealedBox
    except ImportError as e:
        raise FixtureUnavailable(f"PyNaCl not installed: {e}") from e

    try:
        priv = PrivateKey(base64.b64decode(privkey_b64))
        plaintext = SealedBox(priv).decrypt(CIPHERTEXT_PATH.read_bytes())
    except Exception as e:
        raise FixtureUnavailable(f"sealed-box decrypt failed: {e}") from e

    blob = json.loads(plaintext)
    return DevTokenBundle(
        refresh_token=blob["refresh_token"],
        client_id=blob["client_id"],
        client_secret=blob["client_secret"],
        fhir_base_url=blob["fhir_base_url"],
    )
