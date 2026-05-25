# ADR-0020: Use PF org UUID as the practice identity key

**Status:** Accepted

**Date:** 2026-05-24 (Session 0011)

## Context

The system previously used an invented `practice_id` (e.g., `pilot-001`)
as the partition key across all DDB tables. This required a mapping from
`practice_id` to `pf_org_uuid` in the practices table and added a
concept that exists nowhere outside our system.

The PF FHIR base URL already contains the org UUID:
`https://qa-api.practicefusion.com/fhir/r4/v1/{pf_org_uuid}`. The token
response at onboarding time provides the FHIR base URL, from which the
org UUID is extractable. This UUID is PF's canonical identity for the
practice.

## Decision

Use `pf_org_uuid` (e.g., `b4ab304f-d1ac-4565-8dca-992b589422a7`) as
the partition key in all DDB tables. Drop the invented `practice_id`.

Tables affected:
- `phone_routing`: `phone_number → pf_org_uuid`
- `practices`: `pf_org_uuid → {fhir_base_url, ...}`
- `oauth-tokens`: `pf_org_uuid → {encrypted tokens}`
- `rate-limit`: `pf_org_uuid#ani → count`
- `calls`: `pf_org_uuid + call_id`

The contact flow attribute, Lex session attribute, and Lambda event
field all become `pf_org_uuid` instead of `practice_id`.

## Consequences

- One fewer concept to maintain and explain
- The key is meaningful outside our system (PF support can look it up)
- Session 0012 renames `practice_id` → `pf_org_uuid` across all Python
  code, CDK stacks, tests, and session attributes
- The DDB tables deployed in QA (phone-routing, rate-limit) need rows
  re-keyed or the tables recreated (QA only; no prod data exists)
