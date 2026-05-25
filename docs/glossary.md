# Glossary

Terms that come up frequently in this codebase. When in doubt, link to this file rather than re-explaining.

## Healthcare / FHIR

- **EHR** — Electronic Health Record. Practice Fusion is one.
- **FHIR R4** — HL7's Fast Healthcare Interoperability Resources standard, Release 4. The wire format for healthcare data exchange. JSON over HTTPS, REST-shaped.
- **US Core** — A FHIR Implementation Guide profiling the resources US healthcare systems must support (per ONC certification rules). Practice Fusion advertises US Core 6.1.0.
- **USCDI** — The data classes US-certified EHRs must support. v3 maps to US Core 6.1.
- **CapabilityStatement** — A FHIR resource (returned by `GET {base}/metadata`) describing exactly which resources, search params, and operations a FHIR server supports.
- **`Patient` resource** — FHIR resource for a person receiving care. `Patient.telecom` is contact info; `Patient.birthDate` is DOB; `Patient.identifier` holds MRN.
- **MRN** — Medical Record Number. Per-practice identifier for a patient.
- **PHI** — Protected Health Information. HIPAA-regulated identifiers tied to a person's health data.
- **BAA** — Business Associate Agreement. The contract between AWS and a customer for HIPAA-eligible service use.

## SMART-on-FHIR

- **SMART-on-FHIR** — A spec layered on top of FHIR R4 that defines OAuth 2.0 flows for healthcare apps.
- **Provider App** — A SMART app that a clinician (provider) authorizes; uses `user/` scopes.
- **Patient App** — A SMART app that a patient authorizes for themselves; uses `patient/` scopes.
- **Backend Services** — SMART's `client_credentials` flow with JWKS — unattended access using `system/` scopes.
- **`user/` scopes** — Access on behalf of the authorizing provider. Example: `user/Patient.read`.
- **`system/` scopes** — Unattended access for backend automation. Example: `system/Patient.read`.
- **PKCE** — Proof Key for Code Exchange. Hardens the OAuth `authorization_code` flow against code-interception attacks.
- **`.well-known/smart-configuration`** — Discovery endpoint exposing the SMART server's OAuth metadata.

## AWS

- **Amazon Connect** — AWS's cloud contact center; handles telephony, contact flows, queues.
- **Amazon Connect Health** — A separate AWS service (note the "Health"); not what we're using here. See ADR-0001.
- **Bedrock** — AWS's managed LLM service. Hosts Anthropic Claude, AWS Nova, and other foundation models.
- **Bedrock AgentCore** — AWS's managed agent runtime; runs the voice agent in this project.
- **AgentCore Runtime** — The execution environment within AgentCore where our agent code runs.
- **Nova Sonic** — AWS's speech-to-speech foundation model. Audio in → audio out, no intermediate transcript.
- **Strands Agents SDK** — AWS-native Python SDK for building agents on Bedrock.
- **KVS** — Kinesis Video Streams. Connect streams call audio into a KVS stream that AgentCore consumes.
- **CDK** — AWS Cloud Development Kit. We use CDK TypeScript for all infrastructure.
- **DNIS** — Dialed Number Identification Service. The phone number the caller dialed; we use it to look up which practice they're calling.
- **Contact Flow** — The visual workflow inside Connect that handles a call from arrival to routing.
- **CMK** — Customer-Managed Key (in KMS). We use CMKs (not AWS-managed keys) for all PHI data.

## Project-specific

- **Tool** — A Lambda function the agent can invoke. Three exist: `lookup_patient`, `complete_verification`, `escalate_to_human`.
- **Practice** — A single medical practice tenant; the unit of multi-tenancy in this system.
- **Session** — A discrete period of work by one engineer (or Claude instance) on this repo. Each session ends with a handoff doc in `docs/sessions/`.
- **Pilot** — The first practice live with the system. v1's deliverable.
