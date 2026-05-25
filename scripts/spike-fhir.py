#!/usr/bin/env python3
"""Session 0002 spike — Practice Fusion SMART-on-FHIR end-to-end.

What it does:
  1. Reads creds from .env (at repo root).
  2. Discovers PF's SMART OAuth endpoints via /.well-known/smart-configuration.
  3. Generates a PKCE pair (S256).
  4. Starts a one-shot HTTP listener on http://localhost:8080 to receive the
     OAuth redirect.
  5. Opens the browser to PF's authorization endpoint.
  6. On callback, exchanges the auth code (+ verifier + client_secret) at the
     token endpoint.
  7. Calls GET {base}/Patient?telecom=<phone>&birthdate=<dob> for any test
     patients with phone+DOB filled into .env.
  8. Prints a structured summary and exits.

Reusable pieces (well_known.fetch_smart_configuration, pkce.generate,
normalize_e164) live in their own modules with unit tests; this script just
composes them. Keep it scrappy — it is not deployed.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "oauth" / "src"))
sys.path.insert(0, str(REPO / "tools" / "lookup_patient" / "src"))

import requests  # noqa: E402

from lookup_patient.normalize import PhoneFormatError, normalize_e164  # noqa: E402
from oauth.pkce import generate as pkce_generate  # noqa: E402
from oauth.well_known import fetch_smart_configuration  # noqa: E402


# ---------- env loading (tiny .env parser; no python-dotenv dep) ----------


def load_env(env_file: Path) -> dict[str, str]:
    """Parse a .env file. Supports `KEY=value`; ignores comments and blanks."""
    if not env_file.exists():
        raise SystemExit(f"missing {env_file}")
    out: dict[str, str] = {}
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out[k.strip()] = v
    return out


@dataclass(frozen=True)
class Cfg:
    base: str
    client_id: str
    client_secret: str
    scopes: str
    redirect_uri: str
    test_patients: list[dict[str, str]]


def parse_cfg(env: dict[str, str]) -> Cfg:
    required = ("PF_FHIR_BASE_URL", "PF_CLIENT_ID", "PF_CLIENT_SECRET", "PF_SCOPES", "PF_REDIRECT_URI")
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {missing}")
    patients = []
    for i in (1, 2):
        name = env.get(f"PF_TEST_PATIENT_{i}_NAME", "")
        phone = env.get(f"PF_TEST_PATIENT_{i}_PHONE", "")
        dob = env.get(f"PF_TEST_PATIENT_{i}_DOB", "")
        if name:
            patients.append({"name": name, "phone": phone, "dob": dob})
    return Cfg(
        base=env["PF_FHIR_BASE_URL"],
        client_id=env["PF_CLIENT_ID"],
        client_secret=env["PF_CLIENT_SECRET"],
        scopes=env["PF_SCOPES"],
        redirect_uri=env["PF_REDIRECT_URI"],
        test_patients=patients,
    )


# ---------- one-shot OAuth callback listener ----------


class _CallbackState:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    done: threading.Event = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    state_ref: _CallbackState

    def log_message(self, fmt, *args):  # silence default access logs
        pass

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        self.state_ref.code = (params.get("code") or [None])[0]
        self.state_ref.state = (params.get("state") or [None])[0]
        self.state_ref.error = (params.get("error") or [None])[0]
        body = (
            "<html><body><h2>OAuth callback received.</h2>"
            "<p>You can close this tab.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.state_ref.done.set()


def wait_for_callback(redirect_uri: str, expected_state: str, timeout: float = 300.0) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080
    state = _CallbackState()
    handler_cls = type("H", (_Handler,), {"state_ref": state})
    httpd = HTTPServer((host, port), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"  → listening on {redirect_uri} ...")
    try:
        if not state.done.wait(timeout=timeout):
            raise SystemExit("timed out waiting for OAuth callback")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    if state.error:
        raise SystemExit(f"authorization error: {state.error}")
    if not state.code:
        raise SystemExit("callback hit but no code returned")
    if state.state != expected_state:
        raise SystemExit(f"state mismatch: got {state.state!r}, expected {expected_state!r}")
    return state.code, state.state


# ---------- main spike flow ----------


def main() -> int:
    print("== Session 0002 — PF FHIR spike ==\n")

    env = load_env(REPO / ".env")
    cfg = parse_cfg(env)
    print(f"[1/6] env loaded: base={cfg.base}")

    print("[2/6] SMART discovery ...")
    smart = fetch_smart_configuration(cfg.base)
    print(f"   authorization_endpoint = {smart.authorization_endpoint}")
    print(f"   token_endpoint         = {smart.token_endpoint}")
    if not smart.supports_pkce_s256():
        raise SystemExit("PF must support PKCE S256 — aborting.")

    pkce = pkce_generate()
    state = secrets.token_urlsafe(24)
    auth_params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scopes,
        "state": state,
        "aud": cfg.base,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
    }
    auth_url = smart.authorization_endpoint + "?" + urllib.parse.urlencode(auth_params)

    print("\n[3/6] opening browser for authorization ...")
    print(f"   if it doesn't open, visit:\n   {auth_url}\n")
    webbrowser.open(auth_url)

    print("[4/6] waiting for callback ...")
    code, _ = wait_for_callback(cfg.redirect_uri, expected_state=state)
    print(f"   got auth code: {code[:8]}...")

    print("\n[5/6] exchanging code for tokens ...")
    token_resp = requests.post(
        smart.token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "code_verifier": pkce.verifier,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if token_resp.status_code != 200:
        print(f"  ! token endpoint returned {token_resp.status_code}: {token_resp.text[:500]}")
        return 1
    tokens: dict[str, Any] = token_resp.json()
    access = tokens.get("access_token")
    if not access:
        print(f"  ! no access_token in response: {tokens}")
        return 1
    print(f"   access_token: {access[:12]}... ({tokens.get('token_type','?')})")
    print(f"   expires_in:   {tokens.get('expires_in')}")
    print(f"   refresh:      {'yes' if tokens.get('refresh_token') else 'no'}")
    print(f"   scope:        {tokens.get('scope','(none returned)')}")

    # Session 0004 ADR-0007 validation gate: drop the full token pair to a
    # gitignored file so the integration test can pick them up without manual
    # copy-paste. `secrets/` is in .gitignore.
    secrets_dir = REPO / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    secrets_path = secrets_dir / "pf-qa-tokens.json"
    secrets_path.write_text(json.dumps({
        "access_token": access,
        "refresh_token": tokens.get("refresh_token"),
        "expires_in": tokens.get("expires_in"),
        "scope": tokens.get("scope"),
        "fhir_base_url": cfg.base,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }, indent=2))
    print(f"   wrote: {secrets_path}")

    print("\n[6/6] patient discovery + verification-search characterization ...")
    if not cfg.test_patients:
        print("   no test patients configured — skipping.")
        _write_summary(tokens, [], cfg)
        return 0

    results = []
    for p in cfg.test_patients:
        name = p["name"]
        print(f"\n   == {name} ==")
        discovered = _name_search(cfg.base, access, name)
        if discovered is None:
            print(f"     name search: no match")
            results.append({"name": name, "error": "name search: no match"})
            continue
        print(f"     name search → id={discovered['id']}")
        print(f"     stored telecom: {discovered['telecom_raw']}")
        print(f"     stored birthDate: {discovered['birthDate']!r}")
        print(f"     first phone value: {discovered['phone']!r}")

        # Characterize the `Patient?telecom=` search behavior. Each variant
        # tests a different format hypothesis. We report which variants
        # successfully return the patient by ID.
        stored_phone = discovered["phone"] or ""
        digits = "".join(ch for ch in stored_phone if ch.isdigit())
        variants: list[tuple[str, str]] = []
        if stored_phone:
            variants.append(("stored_literal", stored_phone))
        if digits:
            variants.append(("digits_only", digits))
            if len(digits) == 10:
                variants.append(("e164_us", f"+1{digits}"))
                variants.append(("dashed", f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"))
                variants.append(("paren_space", f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"))

        dob = discovered["birthDate"] or ""
        probe_results: list[dict[str, Any]] = []
        target_id = discovered["id"]
        for label, value in variants:
            r = requests.get(
                f"{cfg.base}/Patient",
                params={"telecom": value, "birthdate": dob} if dob else {"telecom": value},
                headers={"Authorization": f"Bearer {access}", "Accept": "application/fhir+json"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"     telecom probe [{label}={value!r}]: HTTP {r.status_code}")
                probe_results.append({"label": label, "value": value, "http_status": r.status_code, "found": False})
                continue
            bundle = r.json()
            ids = [
                e.get("resource", {}).get("id")
                for e in bundle.get("entry") or []
                if e.get("resource", {}).get("resourceType") == "Patient"
            ]
            hit = target_id in ids
            mark = "✓" if hit else "·"
            print(f"     {mark} telecom probe [{label}={value!r}]: total={bundle.get('total')} hit={hit}")
            probe_results.append({"label": label, "value": value, "total": bundle.get("total"), "found": hit})

        results.append({
            "name": name,
            "id": target_id,
            "stored_telecom": discovered["telecom_raw"],
            "stored_birthDate": discovered["birthDate"],
            "telecom_probes": probe_results,
        })

    _write_summary(tokens, results, cfg)
    return 0


def _name_search(base: str, access: str, full_name: str) -> dict[str, Any] | None:
    """Search Patient by given+family name, return id, phone, birthDate and the raw telecom array of the first match."""
    parts = full_name.strip().split()
    if not parts:
        return None
    given = parts[0]
    family = parts[-1]
    r = requests.get(
        f"{base}/Patient",
        params={"family": family, "given": given},
        headers={"Authorization": f"Bearer {access}", "Accept": "application/fhir+json"},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"     ! name search HTTP {r.status_code}: {r.text[:200]}")
        return None
    bundle = r.json()
    entries = bundle.get("entry") or []
    if not entries:
        return None
    patient = entries[0].get("resource", {})
    if patient.get("resourceType") != "Patient":
        return None
    telecoms = patient.get("telecom") or []
    phone = next(
        (t.get("value") for t in telecoms if t.get("system") == "phone" and t.get("value")),
        next((t.get("value") for t in telecoms if t.get("value")), None),
    )
    return {
        "id": patient.get("id"),
        "phone": phone,
        "birthDate": patient.get("birthDate"),
        "telecom_raw": telecoms,
    }


def _write_summary(tokens: dict[str, Any], results: list[dict[str, Any]], cfg: Cfg) -> None:
    summary = {
        "token": {
            "token_type": tokens.get("token_type"),
            "expires_in": tokens.get("expires_in"),
            "has_refresh": bool(tokens.get("refresh_token")),
            "scope": tokens.get("scope"),
        },
        "patient_lookups": results,
        "fhir_base_url": cfg.base,
    }
    out = REPO / "docs" / "research" / "spike-fhir-result.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n   summary written to {out.relative_to(REPO)}")


if __name__ == "__main__":
    sys.exit(main())
