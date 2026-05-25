# ADR-0014: Per-practice dedicated DID + `phone_routing` table as the canonical multi-tenancy router

**Status:** Accepted

**Date:** 2026-05-23 (Session 0007)

**Related:** ADR-0011 (pivot), ADR-0008 (env-context CDK), ADR-0009
(audit + rate-limit).

## Context

Up to Session 0006, every per-practice store was already keyed on
`practice_id`: `practices_store` (FHIR base URL, client secret ARN,
token endpoint), `token_store` (access + refresh tokens),
`disclosure_log` (audit records), `rate_limit` (per-(practice, ANI)
budget). The chain is multi-tenant from the data layer down.

The gap, surfaced in Session 0007 planning: **how does the call entry
point know which `practice_id` to use?** Without an explicit answer,
the contact flow would hardcode a single practice, or guess from ANI
(spoofable, ambiguous), or worse — assume a single tenant.

Two plausible designs:

- **Shared DIDs with caller-ID-based routing.** One Connect number
  serves all practices; the contact flow maps the caller's ANI to
  their practice. **Rejected** — ANI is spoofable, the same caller can
  be a patient at multiple practices, and audit-trail attribution
  gets noisy.
- **Per-practice dedicated DID with a routing table.** Each practice
  gets its own number. A small DDB table maps DID → practice_id; the
  contact flow looks it up at call start. Clean, deterministic,
  brandable (the number lives on the practice's website).

## Decision

**Every practice gets a dedicated DID.** Mapping is held in a new
DDB table `phone_routing`:

```
phone_routing
  PK: phone_number          (E.164, e.g. "+15551234567")
  attrs:
    practice_id             (string, FK to practices_store)
    claimed_at              (ISO8601 timestamp)
    status                  ("active" | "released")
    connect_instance_id     (the Connect instance the DID is claimed
                             against — single instance today, but the
                             column future-proofs multi-instance)
```

**Lifecycle:**

1. **Write at onboarding** (Session 0008's OAuth onboarding API).
   On a successful PF OAuth grant, the API:
   a. Writes the `practices_store` row.
   b. Writes the `token_store` row.
   c. Calls `connect.claim_phone_number` for a US DID against the
      current Connect instance.
   d. Writes the `phone_routing` row keyed on the new DID.
   e. Returns the DID to the practice so they can publish it.
2. **Read at every call.** The Connect contact flow reads
   `$.SystemEndpoint.Address`, performs a `DynamoDB GetItem` via
   Connect's native `InvokeAWSService` integration (no glue Lambda),
   and sets `practice_id` as a contact attribute. The native AI agent
   then receives `practice_id` and forwards it into every MCP tool
   call as a required input.
3. **Soft-delete on offboard.** Mark `status = "released"`. The DID
   itself is released back to AWS via `connect.release_phone_number`
   in a separate operational step (not in the synchronous offboard
   path; AWS may keep the number reserved for a cooldown period).

**A new package `routing/` owns `phone_routing_store.py` with three
operations:** `claim(phone_number, practice_id, connect_instance_id)`,
`resolve(phone_number) -> practice_id | None`, `release(phone_number)`.
moto-mocked unit tests. New CDK stack `infra/lib/phone-routing-stack.ts`
provisions the table — PAY_PER_REQUEST, PITR in prod (mirrors
`rate-limit-stack.ts` pattern from ADR-0008).

## Multi-tenancy chain (explicit, end to end)

```
DID dialed
   → phone_routing.resolve(DID) → practice_id
   → practices_store.get(practice_id) → fhir_base_url, token_endpoint,
                                         pf_client_id, pf_client_secret_arn
   → token_store.get(practice_id)     → access_token, refresh_token,
                                         expires_at
   → rate_limit.check_and_increment(practice_id, ANI)
   → audit.disclosure_log.record({practice_id, ...})
   → fhir_client.search_patient(...)  (uses per-practice base URL +
                                       tokens; respects ADR-0006)
```

Zero hardcoded mappings. Every store keyed on the same `practice_id`.
Every disclosure record, every rate-limit decision, every FHIR call
carries the correct tenant from the moment the call hits Connect.

## Cost note (open question, not blocking)

At ~$1/DID/month and 20K practices, dedicated DIDs cost ~$240K/year
in DID rental alone. This is material but not absurd for a healthcare
SaaS product. We accept the cost for v1 and the pilot, with the
intent to revisit at pilot economics — possible mitigations include:

- DID pooling for low-volume practices (multiple practices share one
  DID, disambiguated by IVR — re-introduces some of the rejected
  caller-ID-routing ambiguity, but on a contained subset).
- Negotiated bulk pricing with AWS for high-DID-count Connect customers.
- A future ADR will own this revisit if/when it triggers.

## Consequences

**Good**

- Multi-tenancy chain is data-driven end to end. No hardcoded
  mappings anywhere in the runtime path.
- Branding-friendly (practices publish their own number on their
  website).
- Audit attribution is unambiguous (DID is the canonical tenant
  pointer at call start).
- Onboarding flow is a single atomic ceremony (Session 0008): OAuth
  grant → DID claim → table writes → DID returned to practice.

**Less good**

- ~$1/DID/month per practice. Not negligible at 20K-practice scale.
- DID claim is rate-limited by AWS (per region, per Connect instance);
  bulk onboarding at scale will need to be chunked. We discover the
  exact rate limits empirically in Session 0008 / 0014.
- DIDs are not infinitely available; population growth eventually
  forces a second Connect instance or a different supply. Acceptable
  for v1 and pilot.

## What this ADR does NOT decide

- The Connect contact-flow JSON authoring (Session 0007 stacks).
- How DIDs are released back to AWS on practice offboard (covered
  operationally, no ADR needed).
- The cost-mitigation strategy at scale (deferred to a future ADR).

## Related

- ADR-0009 — audit + rate-limit at the tool boundary (already keyed
  on practice_id; no schema change).
- ADR-0011 — pivot (this ADR fills the multi-tenancy gap the pivot
  surfaced).
- ADR-0008 — env-context CDK pattern (phone-routing-stack follows it).
