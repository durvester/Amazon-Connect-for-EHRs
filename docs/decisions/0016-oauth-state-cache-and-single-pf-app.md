# ADR-0016: OAuth state cache is a DDB table with TTL; one PF Provider App per environment

**Status:** Accepted

**Date:** 2026-05-23 (Session 0008)

**Related:** ADR-0007 (user-scope refresh validated), ADR-0014 (per-
practice DID + phone_routing), ADR-0015 (FastAPI on Lambda).

## Context

The SMART authorization-code flow generates a fresh `state` value +
PKCE pair on `/oauth/start`, then must remember those values across a
human's browser session for the eventual `/oauth/callback`. The
callback also needs the practice identifier, the discovered SMART
endpoints, and a pointer to the PF client secret. Two questions:

1. Where does this in-flight state live between the two requests?
2. How many PF Provider App registrations do we operate, and how do
   their secrets get to the Lambda?

## Decision

### 1. State cache: a dedicated DDB table

The `oauth-state` table (created by ApiStack — ADR-0015) is keyed on
`state` (the OAuth nonce) and stores:

- `practice_id`
- `code_verifier` (the PKCE half that never left us)
- `fhir_base_url`, `token_endpoint` (cached from SMART discovery so
  the callback doesn't repeat it)
- `pf_client_id`, `pf_client_secret_arn`
- `ttl` (epoch seconds — DDB TTL attribute, set to 10 minutes by
  default)

`OAuthStateStore.consume(state)` is implemented as a conditional
`DeleteItem` with `ReturnValues=ALL_OLD` — atomic single-use semantics
with no race window. A second callback with the same state finds an
empty `Attributes` field and returns None; the API surfaces this as a
400 ("unknown or already-consumed state"). Idempotency-by-design: a
replay can't double-claim a DID or rewrite tokens.

### 2. One PF Provider App per environment

V1 operates a single PF Provider App registration per environment (qa
/ staging / prod). Its `client_id` is plaintext config; its
`client_secret` is stored in Secrets Manager and read by the Lambda
at exchange time. Every practice's `practices_store` row points at
the *same* `pf_client_secret_arn` (i.e. the per-environment app).

## Why DDB for the state cache

Plausible alternatives:

- **Encrypted cookie back to the practice's browser.** Requires
  cookie-flow plumbing and a server-side encryption key with rotation.
  Not worth it for two requests and a TTL'd record.
- **ElastiCache / Redis.** Persistent connections, VPC, more infra.
  Overkill for ~one in-flight state row per pending onboarding —
  expected concurrency is single digits.
- **In-process memory.** Fails on Lambda cold starts and any horizontal
  scale. Non-starter.

DDB has the right shape: PAY_PER_REQUEST scales to zero when nobody is
onboarding, TTL handles abandoned flows without a janitor, the same
service powers every other tenant store, and IAM grants are uniform.

## Why one PF Provider App, not one per practice

PF's Provider App model is a developer-side registration, not a
per-customer one. Asking PF to mint 20K Provider Apps (one per
practice) would not scale at PF's end. The PF token endpoint binds
*tokens* to a practice through the scope + user identity, not
through separate `client_id`s.

The `practices_store` row still carries `pf_client_id` +
`pf_client_secret_arn` as columns — they happen to be identical
across rows in v1, but the schema accommodates future fan-out (e.g.
a separate PF Provider App for staff vs. patient-facing surfaces, or
a regional split).

## Trade-offs

- A leaked PF client secret compromises *every* practice's
  authorization flow, not just one. We rely on Secrets Manager's
  IAM gate + KMS-at-rest + Lambda env isolation. Acceptable for v1;
  if PF makes per-tenant apps cheap later, we re-evaluate.
- DDB TTL is best-effort, not exact (PF docs: typically within 48
  hours, occasionally longer). Abandoned state rows are functionally
  harmless (single-use semantics already block replay) — TTL is for
  hygiene, not security. We don't depend on TTL precision.

## Kill criteria

- If a security review finds a per-practice client secret
  requirement, fan the column out and provision N apps.
- If state-cache reads become hot enough to need <5ms p99 (unlikely —
  this is one read per onboarding), revisit Redis.
