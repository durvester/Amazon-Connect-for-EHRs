# oauth/

SMART-on-FHIR OAuth onboarding service for Practice Fusion. One-time per practice: a provider clicks "Connect Practice Fusion" in the dashboard, completes `authorization_code` + PKCE against Practice Fusion's authorization endpoint, and we store the resulting refresh token (KMS-encrypted) for runtime use.

Endpoints (implemented in Session 0006):
- `GET  /authorize?practice_id=...` — initiate flow
- `GET  /callback?code=...&state=...` — handle PF redirect, exchange code, store tokens
- `POST /refresh` — admin endpoint to force a refresh

## Files

- `src/oauth/pkce.py` — PKCE verifier/challenge generation (implemented in Session 0001 as TDD seed)
- `src/oauth/well_known.py` — SMART discovery (Session 0002)
- `src/oauth/routes.py` — FastAPI routes (Session 0006)
- `src/oauth/token_store.py` — KMS-encrypted refresh-token storage in DynamoDB (Session 0006)

See [docs/architecture.md](../docs/architecture.md) for the full OAuth flow and [docs/credentials.md](../docs/credentials.md) for what credentials this service holds.
