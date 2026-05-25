# Context

## Who and what

**Practice Fusion** is a cloud EHR serving roughly 20,000 independent practices. This project builds an **AWS-native automated patient verification system** for inbound calls to those practices — caller dials in, an AI voice agent verifies their identity against the practice's Practice Fusion record, and routes them to a human queue with patient context attached.

The first deliverable is a pilot with **one practice**. Multi-tenant scale-out comes later.

## The problem we're solving

Independent practices have a chronic inbound-call problem: front desks are overwhelmed, calls hit voicemail and abandon, callers land in the wrong queue. Before any care or scheduling can happen, a human has to verify the caller's identity against the patient record. That verification step alone consumes meaningful staff time and is a leading cause of call abandonment.

Automating verification specifically (not the whole call) gives the biggest near-term win while keeping the v1 scope narrow.

## Decisions that shaped the architecture

| Date | Decision | Why | Where to read more |
|---|---|---|---|
| 2026-05-22 | **Not Amazon Connect Health** | Public AWS docs hard-wire the Patient Verification agent to Epic FHIR APIs; no public knob for non-Epic FHIR servers. | [ADR-0001](decisions/0001-bedrock-agentcore-over-lex.md) |
| 2026-05-22 | ~~Not Amazon Lex~~ → **Lex V2 with Nova 2 Sonic** | Session 0010 discovered the "Connect native AI agent" doesn't exist for voice. Lex + Nova Sonic is the actual voice surface. | [ADR-0018](decisions/0018-lex-orchestrates-nova-sonic-and-agentcore.md) |
| 2026-05-22 | **Amazon Nova 2 Sonic for speech-to-speech** | Configured on Lex bot locale via `UnifiedSpeechSettings`. Nova Sonic v1 is legacy (EOL Sep 2026); using v2. | [ADR-0002](decisions/0002-nova-sonic-over-transcribe-polly.md) |
| 2026-05-23 | **SMART-on-FHIR Provider App (authorization_code + PKCE, user scopes)** | Practices grant access once via clinician sign-in; validated that user-scope refresh tokens work for unattended reads (ADR-0007). | [ADR-0003](decisions/0003-smart-provider-app-not-backend-services.md) |
| 2026-05-23 | ~~Python + Strands Agents SDK~~ → **Lambda code-hook** | Strands/AgentCore Runtime superseded. Lex code-hook Lambda handles dialog logic. | [ADR-0018](decisions/0018-lex-orchestrates-nova-sonic-and-agentcore.md) |
| 2026-05-23 | **CDK TypeScript for all infra** | One IaC language across the stack. | [ADR-0005](decisions/0005-cdk-typescript-for-infra.md) |
| 2026-05-24 | **Lex bot orchestrates; code-hook Lambda bridges to AgentCore Gateway** | Primary-source verified: no `connect:CreateAIAgent`, no `InvokeAIAgent` flow action. Lex + Lambda code-hook is the correct path. | [ADR-0018](decisions/0018-lex-orchestrates-nova-sonic-and-agentcore.md) |

## Scope of v1 (the pilot)

**In scope:**
- One pilot practice with a forwarded DID
- Inbound caller verification using phone + DOB (additional factor configurable per ADR-0003)
- SMART-on-FHIR OAuth onboarding flow (one-time per practice)
- A minimal practice-facing dashboard to (a) connect the FHIR app and (b) review call outcomes
- Audit logging of every PHI disclosure to a write-once S3 bucket

**Out of scope (deferred):**
- Appointment management, refills, clinical Q&A
- EHR write-back
- Multi-practice rollout, self-service onboarding portal, billing/chargeback
- Multi-language support (English only)
- Outbound calls (reminders, recall campaigns)
- Multi-region resilience (us-east-1 only in v1)

## Working assumptions to validate in Session 2

- Practice Fusion's FHIR R4 endpoint accepts `Patient?telecom=&birthdate=` and returns at most one match for a uniquely-identified test patient. (Public CapabilityStatement excerpt suggests yes; live `metadata` will confirm.)
- Veradigm allows user-scope tokens to be used for unattended (phone-time) reads, i.e., the agent operating on the authorizing clinician's behalf is acceptable. If not, we pivot to SMART Backend Services (system scopes) — a clean ADR change.
- AWS BAA covers account `086514900943` (verified via AWS Artifact before any PHI flows).

## Why this matters

Solving verification first — cleanly, with strong audit, with PHI-safe defaults — earns the right to extend the agent into appointment management, refills, and other patient-engagement flows later. Getting v1 right is more important than getting v1 broad.
