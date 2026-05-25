# Credentials

Single source of truth for every credential this system holds, who provides it, and where it lives at rest.

## From Practice Fusion / Veradigm (user provides)

| Credential | Where used | Lives at rest | Notes |
|---|---|---|---|
| `PF_FHIR_BASE_URL` | OAuth flow, `lookup_patient` Lambda | DynamoDB `practices.fhir_base_url` | Per-practice. Pattern: `https://api.practicefusion.com/fhir/r4/v1/{pf_org_uuid}`. Not secret. |
| `PF_CLIENT_ID` | OAuth flow | DynamoDB `practices.pf_client_id` | Not secret. |
| `PF_CLIENT_SECRET` | OAuth token exchange + refresh | AWS Secrets Manager (one secret per environment) | KMS-encrypted. Lambda fetches at cold-start. |
| `PF_SCOPES` | OAuth `/authorize` request | Code constant (overridable per practice via env) | Default proposed: `user/Patient.read openid fhirUser offline_access`. Final string to be confirmed with Veradigm in Session 2. |
| Practice's `pf_org_uuid` | URL substitution into `PF_FHIR_BASE_URL` | DynamoDB `practices.pf_org_uuid` | One per pilot practice. |

### What we need to give back to Veradigm to register the app

A single **OAuth redirect URI**. Plan:

- **Session 2 spike (local dev):** `http://localhost:8080/oauth/callback`. Many SMART servers allow `http://localhost` redirects for development; confirm with Veradigm. If not allowed, we accelerate the API Gateway setup and use the production URI.
- **Pilot / production:** `https://api.<host>/oauth/callback`. `<host>` will be a stable hostname behind API Gateway, chosen in Session 6 and given to Veradigm before registration.

## Derived at runtime (from PF, no secrets)

Discovered via `GET {PF_FHIR_BASE_URL}/.well-known/smart-configuration` (fall back to `.../openid-configuration`):

- `authorization_endpoint`
- `token_endpoint`
- `revocation_endpoint`
- `jwks_uri`
- supported `scopes_supported`, `response_types_supported`, `grant_types_supported`

These are cached in-memory per Lambda invocation; no need to persist.

## OAuth tokens (user grant, stored encrypted)

| Credential | Where used | Lives at rest | Notes |
|---|---|---|---|
| PF access token | `lookup_patient` (Authorization header) | DynamoDB `oauth-tokens.access_token_ciphertext` (KMS-encrypted via `oauth-key` CMK) | Cached until expiry. |
| PF refresh token | OAuth refresh flow | DynamoDB `oauth-tokens.refresh_token_ciphertext` (KMS-encrypted) | The crown jewel — leak = practice-wide PHI access. CMK key policy restricts decrypt to the OAuth and `lookup_patient` Lambda roles only. |

## From AWS (we own and manage)

| Credential | Purpose | Lives at rest |
|---|---|---|
| AWS account `086514900943` | Development + pilot account | — |
| AWS region | `us-east-1` for v1 | — |
| KMS CMK `phi-key` | Encrypt PHI artifacts (S3 transcripts/audio, `calls` table) | Created by CDK; ARN stored in CDK stack outputs |
| KMS CMK `oauth-key` | Encrypt OAuth tokens | Created by CDK |
| Cognito user pool | Practice-staff login to dashboard | Created by CDK |
| Cognito app client | Dashboard ↔ Cognito | Created by CDK |
| IAM roles | One per Lambda, least-privilege | Created by CDK |
| API Gateway domain name | OAuth + practice API | Created by CDK once domain chosen |
| Connect instance ARN | Telephony | Created by CDK |
| Connect DIDs | Inbound phone numbers (one per pilot practice) | Claimed via Connect API in CDK |

## Storage rules (non-negotiable)

1. **No secrets in env vars at rest.** `.env.example` shows env-var names without values; `.env` is in `.gitignore`. Production Lambdas fetch from Secrets Manager at cold-start.
2. **No secrets in source.** Pre-commit hook (`detect-secrets` in CI) blocks accidental commits.
3. **KMS-CMK encryption everywhere PHI flows.** Default-managed keys are not used for PHI artifacts.
4. **Refresh-token KMS key policy is the most restricted.** Only OAuth-onboarding and `lookup_patient` Lambda roles can `kms:Decrypt`. No human IAM principals (including admins) by default — break-glass via a separate audited path.
5. **No secrets in CloudWatch logs.** Audit Lambda log output during code review.

## Where local-dev credentials live

For Session 0002's local CLI spike, credentials live in `.env` at the repo root. `.env` is gitignored. `.env.example` documents the shape and is committed.

Loading pattern (Python):

```python
from dotenv import load_dotenv
load_dotenv()   # picks up .env at repo root
```

Production (Sessions 0006+) replaces this with Secrets Manager fetches at Lambda init.

## Session 1 status

`.env` has been **hydrated** with Practice Fusion **QA** credentials for the pilot test practice:
- `PF_FHIR_BASE_URL` — QA endpoint with the test-practice `org-uuid`
- `PF_CLIENT_ID`, `PF_CLIENT_SECRET` — registered with Veradigm
- `PF_SCOPES` — 20-scope string including `launch`, `user/Patient.read`, `openid`, `offline_access`, `fhiruser`, and read scopes for the other US Core resources we may need later (Condition, Encounter, Observation, etc.). For Session 0002 only `user/Patient.read openid offline_access` is exercised; the others come into play in later sessions.
- `PF_REDIRECT_URI=http://localhost:8080/oauth/callback` — confirmed registered with Veradigm
- Test patient names captured; phone + DOB to be added before running the spike

AWS BAA check on account `086514900943` remains pending — required before Session 0006 (production OAuth service deploy).
