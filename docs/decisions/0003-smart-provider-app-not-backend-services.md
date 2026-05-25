# ADR-0003: SMART-on-FHIR Provider App (`authorization_code` + PKCE, user scopes) — not Backend Services

**Status:** Accepted (to be confirmed with Veradigm in Session 2)
**Date:** 2026-05-23

## Context

Practice Fusion exposes a SMART-on-FHIR R4 server. Two ways an automated agent can authenticate:

1. **Provider App** — `authorization_code` flow with PKCE. A clinician (provider) at the practice signs into our dashboard, redirects to Practice Fusion to grant `user/` scopes, redirects back with an authorization code which we exchange for an access token + long-lived refresh token. We hold one refresh token per practice and mint access tokens as needed.
2. **Backend Services** — `client_credentials` flow with JWKS. No user interaction. The app is registered with `system/` scopes; the app proves identity by signing a JWT with its private key, gets back an access token. Used for batch/unattended access.

The runtime-access pattern here is unattended — a phone call arrives, the agent calls FHIR, the patient on the line is not the OAuth user.

## Decision

Use the **Provider App pattern with `user/` scopes**, per user direction. The provider's one-time grant is reused via the refresh token for every subsequent call against that practice.

## Why

- **User direction.** The user explicitly named "user scopes since this is a provider app."
- **Aligns with how the dashboard works.** The practice's provider signs into the dashboard anyway; the OAuth grant happens in that same flow. No separate JWKS or pre-shared-key setup.
- **Lower onboarding friction.** Practice admins do not need to provision a backend service identity; they just click "Connect Practice Fusion" in our UI.

## Consequences

**Positive:**
- Simple per-practice onboarding — one OAuth grant per practice, then runs unattended.
- Audit trail clearly attributes reads to the authorizing provider.

**Negative / open question:**
- **Does Veradigm allow `user/` scope tokens to be used in unattended (phone-time) contexts?** Some SMART servers consider that pattern out-of-policy and require Backend Services for it. **This is the central question for Session 2.** If Veradigm requires Backend Services, we replace this ADR.
- Refresh-token TTL must be managed; if it expires we must surface "needs reconnect" to the practice in the dashboard.
- We must store refresh tokens — the encryption posture (KMS CMK, restricted key policy) is in `docs/architecture.md`.

## Alternatives considered

- **Backend Services (system scopes).** Operationally cleaner for unattended access, but the user explicitly chose Provider App. Keep as the fallback if Veradigm rejects user-scope unattended use.
- **Hybrid (Provider App for onboarding, Backend Services for runtime).** Over-complicated for v1; revisit only if Veradigm forces it.

## Validation criteria

Session 2: confirm with Veradigm that user-scope refresh tokens are acceptable for the unattended phone-agent reads. If yes, this ADR stands. If no, replace with ADR-0006 documenting the Backend Services pivot.
