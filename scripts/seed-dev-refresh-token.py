"""Seed/refresh the sealed-box-encrypted dev refresh-token fixture (QA-only).

Reads `secrets/pf-qa-tokens.json` (gitignored — manually populated by
running `make spike-fhir` once) and writes a sealed-box ciphertext to
`secrets/pf-qa-refresh-token.enc`. The public key is also written to
`secrets/dev-fixture-pubkey.b64` and **is intended to be checked in**
(sealed-box: anyone with the public key can encrypt, only the private
key can decrypt).

First run: generates a new keypair, prints the base-64-encoded private
key once to stdout, and exits non-zero so the developer is forced to
copy it into `~/.pf-voice-dev/privkey` (and/or the GitHub Actions
secret `PF_DEV_FIXTURE_PRIVKEY`) before re-running. Subsequent runs
reuse the existing public key and just re-encrypt (e.g., after a token
rotation if PF ever revokes the QA refresh token — currently
non-rotating per Session 0004 findings).

Prod path uses AWS Secrets Manager, not this fixture (architecture.md).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from nacl.public import PrivateKey, PublicKey, SealedBox

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKENS_JSON = REPO_ROOT / "secrets" / "pf-qa-tokens.json"
CIPHERTEXT = REPO_ROOT / "secrets" / "pf-qa-refresh-token.enc"
PUBKEY = REPO_ROOT / "secrets" / "dev-fixture-pubkey.b64"

_REQUIRED = ("refresh_token", "client_id", "client_secret", "fhir_base_url")


def _load_tokens() -> dict[str, str]:
    if not TOKENS_JSON.exists():
        sys.exit(
            f"missing {TOKENS_JSON}; run `make spike-fhir` once to populate it"
        )
    blob = json.loads(TOKENS_JSON.read_text())
    missing = [k for k in _REQUIRED if not blob.get(k)]
    if missing:
        sys.exit(f"{TOKENS_JSON} missing keys: {missing}")
    return {k: blob[k] for k in _REQUIRED}


def _ensure_keypair() -> PublicKey:
    if PUBKEY.exists():
        return PublicKey(base64.b64decode(PUBKEY.read_text().strip()))
    priv = PrivateKey.generate()
    pub = priv.public_key
    PUBKEY.write_text(base64.b64encode(bytes(pub)).decode() + "\n")
    print(f"# wrote new public key to {PUBKEY} (commit this file).")
    print("# new private key (save to PF_DEV_FIXTURE_PRIVKEY env var and Actions secret):")
    print(base64.b64encode(bytes(priv)).decode())
    sys.exit(
        "first-run: re-run after setting PF_DEV_FIXTURE_PRIVKEY so the harness can decrypt"
    )


def main() -> int:
    blob = _load_tokens()
    pub = _ensure_keypair()
    payload = json.dumps(blob, separators=(",", ":")).encode()
    ciphertext = SealedBox(pub).encrypt(payload)
    CIPHERTEXT.write_bytes(ciphertext)
    print(f"# wrote {CIPHERTEXT} ({len(ciphertext)} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
