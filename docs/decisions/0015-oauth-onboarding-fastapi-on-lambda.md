# ADR-0015: OAuth onboarding API runs as FastAPI-on-Lambda behind a Function URL

**Status:** Accepted

**Date:** 2026-05-23 (Session 0008)

**Related:** ADR-0008 (env-context CDK), ADR-0011 (Connect-native pivot),
ADR-0014 (per-practice DID + phone_routing).

## Context

A practice can only become real to the system by completing a SMART-on-
FHIR authorization code grant against Practice Fusion: the human at the
practice clicks through PF's consent UI in a browser, PF redirects back
to us with a `code`, and we exchange that for an access + refresh token
pair scoped to the practice. After that exchange we also have to claim
a dedicated DID (ADR-0014) and write four DDB rows so the multi-tenancy
chain is fully populated before the first inbound call.

Two surfaces are needed:

- `GET /oauth/start` — kicks off the flow (PKCE pair, discovery,
  302 to PF's authorization endpoint).
- `GET /oauth/callback` — receives the `code` from PF, swaps it for
  tokens, writes the four rows, returns the claimed DID.

We need a stable URL PF can be configured to redirect to, in a
HIPAA-eligible service, with the smallest possible attack surface
(two GETs, no authenticated state of our own — the OAuth `state`
nonce is the only thing keeping replays from succeeding).

## Decision

A single Python Lambda runs the api package's FastAPI app via Mangum.
The Lambda is exposed by a **Lambda Function URL** (auth type NONE)
rather than API Gateway.

The api package owns:

- `api.onboarding` — `/oauth/start` and `/oauth/callback` route bodies,
  plus an `OnboardingDeps` dataclass for dependency injection.
- `api.app` — `build_app(deps=None)` factory. With `deps=None` it
  constructs production deps from env vars; tests pass fakes.
- `api.handler` — `Mangum(build_app())` for the Lambda runtime.

Every external dependency (the four DDB stores, the PF code exchange,
the Connect DID claim, the Secrets Manager fetch) is injected so unit
tests can drive the full flow under moto without touching the
network. The Lambda env vars enumerate the table names, the KMS key
id, the Connect instance id + ARN, and the OAuth redirect URI.

## Why Function URL, not API Gateway

The onboarding API is two unauthenticated GETs that exist purely to
shuttle the SMART code grant. We don't need:

- request/response transformations (no model mapping)
- a custom domain *yet* (PF QA accepts the raw `*.lambda-url` host;
  prod gets a CloudFront alias when we cut over)
- request validators, throttling, or WAF beyond what Lambda already
  enforces (the state nonce is the single-use guard)
- multiple stages (env separation is already at the stack level via
  ADR-0008)

API Gateway carries fixed per-month + per-million-request cost +
config surface for none of the above. Lambda Function URLs are GA and
HIPAA-eligible (inherited via Lambda). When Session 0010+ adds the
authenticated practice-dashboard surface, that gets its own API
Gateway (REST API + Cognito) — leaving onboarding on Function URL
keeps the auth-edge minimal.

## Why FastAPI + Mangum, not pure handler functions

The slim refactor of `lookup_patient` (Session 0007) showed that thin
handlers are fine when the route surface is one entrypoint and one
output shape. The onboarding API has at least two routes that share a
lot of state (the DI bundle), and Session 0010+ will add more
(authenticated practice routes, refresh-token health, audit-record
export). FastAPI gives us:

- `TestClient` for the kind of full-app E2E tests Session 0008 leans
  on
- `APIRouter` for hanging future routes off the same Mangum surface
  without refactoring the deployment
- typed parameter parsing for free

Mangum is the standard ASGI-to-Lambda adapter; nothing exotic.

## Trade-offs

- The full DI surface is wordy. `OnboardingDeps` has 10 fields. The
  alternative — globals + monkeypatching in tests — is shorter to
  write but produces worse failures when the production wiring is
  wrong. We pay the verbosity to keep the wiring explicit.
- Function URL means no CloudWatch request validation. We rely on
  FastAPI's parameter parsing to reject malformed inputs (returns 422
  by default). That's a smaller surface than API Gateway's validators
  but it's the right place for the check — closer to the code.

## Consequences

- The Lambda's IAM surface is broad-ish: RW on four tables, KMS
  Encrypt/Decrypt on the tokens CMK, `connect:Search/Claim` against
  `*` (no resource-level grant available for those actions), and
  `secretsmanager:GetSecretValue` on exactly the PF Provider App ARN.
  Anything beyond that goes to a separate Lambda.
- Deploy packaging needs `pip install -t build/` over the api package
  + its dependencies (fastapi, mangum, requests, oauth, routing). The
  current `lambda.Code.fromAsset` config ships only `api/src` — a
  follow-up before the first real deploy must add the build step
  (tracked in Session 0008's open questions).
- The state row is single-use (consume = atomic DDB delete + return).
  A failed DID claim after a successful code exchange wastes the
  state row; recovery is "re-run /oauth/start, get a fresh state."
  The tokens are still good — the practices row + token row are
  persisted *before* the DID claim — so the next attempt finishes
  the missing DID claim + phone_routing write without re-doing the
  PF round-trip if we extend the API in a later session. Today, we
  accept the wasted state.

## Kill criterion

If we add a second public-facing API surface beyond onboarding +
dashboard (e.g. a webhook receiver for PF events), revisit whether a
single API Gateway with multiple routes is cleaner than two Function
URLs.
