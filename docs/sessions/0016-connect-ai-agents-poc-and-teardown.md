# Session 0016 — Connect AI Agents POC evaluation and full teardown

**Date:** 2026-05-25 to 2026-05-26
**Goal (one sentence):** Evaluate Connect AI Agents (ORCHESTRATION type with MCP tools) as an alternative to the code-hook Lambda architecture, then tear down all POC resources.

## What was done

### Connect AI Agents POC (failed — torn down)
- Created ORCHESTRATION AI prompt (`803ee1f3-...`) with custom verification logic adapted for `<message>`/`<thinking>` format
- Created ORCHESTRATION AI agent (`7f2c16b6-...`) with MCP tools + Complete/Escalate
- Created 3 flow module tools (2 CLI, 1 console) wrapping FHIR Lambdas
- Created Lex bot with QInConnectIntent (CLI and console versions)
- Built contact flow with CreateWisdomSession, UpdateContactData, session data injection
- Discovered `list-spans` API for execution traces (the only debugging tool available)
- Tested ~15 live calls, none achieved successful tool execution

### Key findings
- Claude passes correct tool parameters when Custom session variables resolve
- UpdateContactData block required to bind wisdom session to contact (undocumented in admin guide, only in workshop)
- MCP flow module tool execution fails with "Target entity not found" — `create-contact-flow-module-version` does not capture `ExternalInvocationConfiguration`
- Even CONSTANT tools (static string, no dependencies) fail with "Tool execution failed"
- Tool input schemas from flow modules are not forwarded to Claude via the API tools parameter
- The `_N` suffix in tool IDs (`aws_custom_flows__<id>_N`) is opaque and doesn't map to module versions predictably

### Full teardown completed
All Session 15-16 POC resources destroyed:
- DID +16122600546 released, phone_routing row deleted
- Contact flow `pf-voice-poc-qconnect-flow` deleted
- Lex bots: `pf-voice-poc-qconnect` (CLI) + `Newpfbot` (console) deleted
- AI agent `pf-voice-poc-agent` and prompt `pf-voice-poc-verification` deleted
- 3 flow modules deleted (aliases, versions, modules)
- 3 Lambdas deleted (search-patient, get-patient-records, session-data)
- 3 IAM roles deleted (lambda-role, lex-role, bedrock-logging)
- Security profile AllowedFlowModules cleared
- Bedrock model invocation logging disabled, log group deleted
- 4 orphaned CloudWatch log groups deleted
- Orchestrator reset to system default
- `poc/` directory deleted from repo

### Production verified intact
- +16156250631 works, phone_routing intact
- All pf-voice-qa-* Lambdas, tables, and resources untouched
- Only production Lex bot (pf-voice-qa-verification) remains

## Decisions made
- Connect AI Agents ORCHESTRATION with MCP flow module tools is not production-ready (no ADR — POC finding)
- Code-hook Lambda architecture remains the production path
- Confluence page published: "Amazon Connect for Patient Engagement POC" in Technology space

## Open questions
1. Will AWS fix `create-contact-flow-module-version` to capture `ExternalInvocationConfiguration`?
2. Would AgentCore Gateway (instead of flow modules) work for MCP tools? Not tested.
3. Re-evaluate Connect AI Agents in 6 months (Nov 2026)

## Next session pickup

**The first thing the next session should do:**
1. Read this file
2. Read `docs/context.md` and `docs/architecture.md`
3. The POC is done. The production system on +16156250631 works. Next work should focus on production hardening:
   - CDK reconciliation (codify CLI-deployed resources as IaC)
   - Conversation logging (persist transcripts)
   - Token refresh hardening
   - Multi-practice onboarding

**Key resources (production only):**
- Connect instance: `bc48ce14-1766-44c9-807b-4807e6010dd6`
- Production DID: `+16156250631`
- Production Lex bot: `Q8KEE7VWFQ` / alias `HI8OESGPSF`
- Test practice: `pf_org_uuid: b4ab304f-d1ac-4565-8dca-992b589422a7`
- qconnect assistant: `954ffc94-ec76-477e-9a2e-77ab81e054b8` (exists but no custom agents/prompts on it)

## Files changed
- `poc/` directory deleted (7 files)
- `docs/sessions/0016-connect-ai-agents-poc-and-teardown.md` (this file)

## Notes for future Claude
- Connect AI Agents ORCHESTRATION can activate on voice, Claude runs and passes correct parameters, but MCP tool execution is broken as of May 2026.
- The `list-spans` API (`aws qconnect list-spans`) is the only way to debug orchestration agent behavior. It shows LLM calls, tool use arguments, and tool results.
- `UpdateContactData` with `WisdomSessionArn: $.Wisdom.SessionArn` is required after `CreateWisdomSession` — without it, tool execution has no session context.
- `UpdateSessionData` API injects custom data accessible in prompts via `{{$.Custom.<key>}}`.
- Flow module versions created via CLI never have `ExternalInvocationConfiguration` set. This is likely an AWS bug.
- The AWS workshop at `catalog.workshops.aws/amazon-connect-ai-agents` is the best reference for Connect AI Agents setup — the admin guide is incomplete.
