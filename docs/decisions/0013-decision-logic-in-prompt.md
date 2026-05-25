# ADR-0013: Verification decision logic lives in the agent prompt; Lambdas are thin FHIR adapters

**Status:** Accepted (with explicit audit-defensibility plan and a
named kill criterion)

**Date:** 2026-05-23 (Session 0007)

**Related:** ADR-0011 (pivot), ADR-0006 (PF literal telecom-search),
ADR-0009 (audit + rate-limit).

## Context

Prior to this ADR, `tools/lookup_patient/handler.py` returned a typed
verdict — `match: "single" | "none" | "ambiguous"` — and the agent's
job was to relay the verdict to the caller. The match decision (does
"John A. Smith" born 1985-05-14 match the FHIR Patient record we just
fetched?) lived deterministically in code.

In the pivoted architecture (ADR-0011), the Connect native AI agent
*can* reason over a candidate list and decide the match itself. The
question: where does the decision live?

Two clean answers:

- **In the Lambda (the safer default).** Lambda returns
  match/none/ambiguous; prompt relays. Auditable, deterministic,
  framework-agnostic. The Plan agent recommended this. This was the
  prior shape.
- **In the agent prompt.** Lambda returns candidates; prompt reasons
  over them. More flexible (the LLM can handle nuance like "the
  caller said 1985-05-14, the record says 1985-5-14, accept"), but
  introduces LLM non-determinism into a regulated identity gate.

The user explicitly chose the prompt-side option in Session 0007
planning. This ADR records the choice, the reasons, and the audit
plan that makes it defensible.

## Decision

**Verification reasoning — does the caller's name+DOB+phone match a
returned candidate? — lives in the Connect AI agent's system prompt.**

**Each Lambda is a thin FHIR adapter.** Its responsibilities:

- Accept inputs (caller-provided name, DOB, ANI; system-resolved
  `practice_id`).
- Apply rate-limit gate first (ADR-0009 — leak-resistant).
- Resolve per-practice credentials from `practices_store` +
  `token_store` (refresh once on 401).
- Issue FHIR probes against the PF endpoint, respecting ADR-0006's
  literal-telecom rule (this is non-negotiable, lives in the
  `fhir_client`, never moves to the prompt).
- Write one disclosure-log record per FHIR probe (ADR-0009).
- Return a JSON candidate list. Each candidate carries enough fields
  for the prompt to disambiguate: full name, DOB (ISO), masked phone,
  PF patient ID, and a `probe_origin` tag identifying which probe
  surfaced this candidate (e.g., `telecom`, `family+given`).

**The Lambda no longer returns a `match` verdict.** It returns a list,
empty list, or an error/rate-limit/credentials-expired flag.

**The agent's system prompt encodes the verification policy**:

- Confirm exactly one candidate before any disclosure. If the
  candidate list is empty, ask the caller to restate. If multiple,
  ask a disambiguating question (DOB if name matched, phone last
  four if DOB matched).
- Never assume; only confirm. Never read patient data from a
  candidate aloud before the caller confirms it.
- The full prompt text is checked into the repo (`agent/prompts/`)
  and version-controlled. CDK deploys it to the Connect AI agent
  configuration; the deployed prompt and the repo prompt are
  asserted equal in CI (Session 0013).

## Audit defensibility plan

The audit risk is real: an auditor will ask "how do you know the
agent didn't accept a non-match?" The plan:

1. **Every interaction is captured end-to-end** in the existing S3
   Object Lock audit bucket (7-year compliance retention, ADR-0009).
   The recorded artifacts per call:
   - The full caller transcript (Connect provides via S3 export).
   - Every tool invocation: tool name, inputs, output JSON.
   - Every agent decision: the LLM's reasoning trace exposed via
     Connect's agent telemetry (the Connect AI agent emits per-turn
     decision events; we capture them).
   - The final verification outcome and which candidate was confirmed.
2. **Eval set with a fixed corpus** (Session 0013). A regression
   harness exercises the verification prompt against ~200 synthetic
   caller transcripts spanning golden path + ambiguous + no-match +
   spoof attempts + edge cases (typos, accent, phone changes). The
   eval reports the prompt's verdict-stability across runs. We
   commit to ≥99% verdict-stability on the corpus before Session 0014
   pilot dry-run.
3. **Determinism settings.** The Connect AI agent runs Nova Sonic
   with temperature pinned low (0.0–0.2 — exact value tuned in
   Session 0013) for the verification turn. Higher temperatures are
   acceptable for the conversational warmth around the gate, not
   for the gate itself. (If Nova Sonic doesn't expose per-turn
   temperature, the whole agent runs low-temp; tradeoff documented.)

## Kill criterion

If, by the end of Session 0013, the eval suite shows verdict-stability
below 99%, OR a single high-severity audit-defensibility hole is
found (e.g., we can't prove which candidate the agent selected on a
historical call), the decision is **reverted**: restore the
`match` verdict in the Lambda, prune the prompt to relay-only, and
write ADR-0017 documenting the reversion. The cost of the reversion is
contained — the Lambda's slim refactor is one PR's worth of work; the
prompt change is configuration.

## Consequences

**Good**

- The agent can handle nuanced cases (DOB format variance, phone
  format variance, accent-driven name spelling) that brittle code
  would reject.
- The Lambda becomes simpler: search and return; no business logic.
- The same Lambda is reusable for a future non-voice consumer (chat,
  staff dashboard) without forcing a verdict shape that may not fit.

**Less good**

- LLM non-determinism in a regulated gate is a real audit exposure.
  The plan above mitigates; it does not eliminate. We are explicit
  about this tradeoff.
- We pay an upfront eval-suite cost (Session 0013).
- The verification policy lives in two places: the prompt (regulated
  reasoning) and the Lambda (PF quirk handling per ADR-0006). Two
  places is the inherent cost of separating "reasoning" from "data
  access."

## What this ADR does NOT decide

- The exact prompt text. That's a Session 0009 artifact, iterated in
  Sessions 0010–0012.
- The eval corpus contents. Session 0013.
- Whether other regulated decisions (refund eligibility, prescription
  refill rules, etc.) follow this same split. They aren't in v1; if
  added later, each gets its own ADR.

## Related

- ADR-0006 — PF literal-telecom-search rule. Stays in the
  `fhir_client`, never the prompt.
- ADR-0009 — audit + rate-limit. Unchanged.
- ADR-0011 — pivot. ADR-0013 is the verification-specific decision
  that the pivot enables.
