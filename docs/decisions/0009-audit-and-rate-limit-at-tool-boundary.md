# ADR-0009: HIPAA audit log + rate limit live at the tool boundary

**Status:** Accepted

**Date:** 2026-05-23 (Session 0006)

## Context

The roadmap (Session 0006 entry) requires every PHI read after this
session to:

1. **Write an audit record** suitable for HIPAA accounting-of-disclosures.
2. **Pass a per-(practice, ANI) rate-limit check** before the read is
   issued.

Both could live in several places — at the agent layer, at a shared
"FHIR gateway" Lambda, at the tool boundary, or as middleware inside
each tool. This ADR records where they actually live and why.

(Original roadmap numbered this ADR-0008. Renumbered to 0009 because
ADR-0008 is now the multi-env CDK structure decision that constrains
the stacks introduced in the same session.)

## Decision

### Audit log: one record per FHIR call, written by each tool

The audit recorder (``audit.disclosure_log.record``) is invoked **once
per FHIR call** — not once per agent tool invocation, not once per
verification attempt. For ``lookup_patient`` this means one record per
phone-format *probe* (the handler runs up to 6).

Implementation: the FHIR client (``fhir_client.search_patient``)
accepts an ``on_probe`` callback parameter; the handler wires it to
``disclosure_log.record``. The FHIR client itself doesn't know what an
audit record is. The handler doesn't know the inside of the probe
loop. Coupling stays one-way.

Record schema (S3 object body, JSON):

```
practice_id, call_id, timestamp,
tool                  ("lookup_patient" today),
query_template        ("Patient?telecom=<phone>&birthdate=<dob>"),
result_resource_ids   (list of FHIR resource IDs touched),
disclosed_fields      (list of FHIR field names read, never values)
```

**Why one-per-probe, not one-per-lookup:** HIPAA's
accounting-of-disclosures rule cares about "what data was looked at,
when, by whom, for which patient." Six probes against different
phone formats represent six attempts to look at PHI. Collapsing them
into one record loses the audit's resolution — and any failed-probe
diagnostics in production. The DDB write overhead is negligible at
our call volume (one S3 PutObject per probe, ~300 bytes).

**Why the FHIR client uses a callback, not directly imports audit:**
Tools other than ``lookup_patient`` (Sessions 0013–0015) will share
the FHIR-client style but use different audit fields. Keeping
``audit`` out of ``fhir_client``'s imports lets each tool decide
exactly what to record.

### Rate limit: one gate per call, surfaced as a normal "match" outcome

The rate limit (``audit.rate_limit.check_and_increment``) is invoked
**once per handler invocation**, *before* any credentials work or FHIR
call. The check increments and tests atomically (DDB
``ConditionalUpdate``).

Over-budget surfaces as ``match: "rate_limited"`` in the handler's
return shape — the same shape any normal lookup outcome takes. The
agent treats it identically to ``match: "none"``: route to a human.

**Why before credentials / before FHIR:** A caller who's hammering us
shouldn't get to learn that we recognize their phone number. Hitting
PF before the rate-limit check leaks information (timing,
side-effects). The rate check is cheap; the FHIR call is expensive.
Order matches that.

**Why surfaced as ``rate_limited``, not raised as an exception:** The
agent's visible behavior to the caller must be identical to "we
couldn't verify you" regardless of whether a real lookup happened,
failed, or was suppressed. If a bad actor sees timing differences or
distinct agent prompts based on rate-limit state, they can use the
IVR to probe whether a given phone exists in the practice's records.
Leak-resistance is the property; this is the simplest mechanism.

### Default budget: 100 / (practice, ANI, day)

Per the roadmap. Sized for an active patient who might genuinely call
multiple times in a day; impossible to reach with normal use; trivial
to reach with sequential-ANI probing. Adjustable per-env in
``EnvConfig.ratelimitDefaultPerDay``.

A future per-practice override (in the practices_store row) is
plausible — the table for that doesn't exist yet, defer until a
practice asks for it.

## Consequences

### Good
- One row per real PHI disclosure. Auditable, queryable by
  practice + date (the S3 key prefix).
- Rate limit is leak-resistant by construction. Callers cannot
  distinguish "no record" from "rate-limited" from agent behavior.
- Audit and rate-limit are independent packages. Future tools reuse
  them without re-litigating the design.
- The FHIR client stays free of HIPAA-specific imports. It's a
  generic search client with a callback.

### Bad / accepted
- Six DDB writes per "patient not found" lookup. Negligible at v1
  volume; revisit if Sessions 0013–0015 push call volume up.
- The probe-template string is a small magic string that every tool
  needs to maintain consistently. A schema lint test could enforce
  the format-pattern shape; out of scope for v1.
- Rate-limit ConditionalUpdate increments BEFORE returning the cap
  decision. A caller hitting "exactly 100" today will see the
  attempt fail at 101 and immediately be over-budget for the rest of
  the day. Intentional: pre-check + increment would race.

### Migration shape
- Session 0006 introduces both modules and wires them into
  ``lookup_patient``.
- Sessions 0013–0015 each add their tool's audit-callback (different
  ``tool`` and ``query_template`` values) and reuse the same rate
  limit table. No code in those tools touches audit/rate-limit
  internals.
- The audit bucket's compliance-mode Object Lock (ADR-0008 +
  ``infra/lib/audit-stack.ts``) means audit data is tamper-evident
  for 7 years from write. The compliance role added in Session 0016
  is the only thing that gets read access.

## Alternatives considered

- **Audit at the agent layer (one record per agent tool call).**
  Rejected: too coarse — multi-probe lookups would write one record
  for an arbitrary number of PF reads, defeating the resolution.
- **A shared "FHIR gateway" Lambda that every tool calls and that
  owns audit + rate-limit centrally.** Rejected: an extra Lambda
  hop costs ~50 ms minimum and adds an IAM seam without simplifying
  anything (each tool already knows its own tool name + template).
- **Synchronous "audit failed → fail the lookup" semantics.**
  Considered but deferred: today an S3 PutObject failure is logged
  and the FHIR call still proceeds. HIPAA requires the disclosure
  *be recorded*, not that the disclosure be blocked on the recorder.
  When the audit bucket is unreachable, the right answer is alarm
  the operator, not refuse the call. Alarm + DLQ wiring in Session
  0016.
- **Block on rate-limit by returning a specific HTTP-style status
  back through the agent.** Rejected per leak-resistance above.

## Open questions

- **Per-practice rate-limit overrides** — when a pilot practice
  legitimately exceeds 100/day, how do they get a higher cap? Plausible
  answer: a column on the practices row, but no practice is asking
  yet. Defer.
- **Audit-bucket read access for the practice itself** — practices
  may eventually want to see their own accounting-of-disclosures
  records. Today only the compliance role can read. Decide when a
  practice asks.
