# Cost Model

Infrastructure cost estimates for the voice agent. Source of truth — any Confluence page or write-up should reference these numbers rather than restate them.

## Assumptions

- 200 inbound calls per practice per month
- Average call length 90 seconds (1.5 minutes)
- ~3 LLM turns per call, ~2K tokens per turn (mixed input/output)
- One dedicated DID per practice
- DynamoDB in PAY_PER_REQUEST mode
- us-east-1 pricing as of May 2026

## Per-Practice Monthly Cost — Baseline

| Component | Assumption | Cost |
| --- | --- | --- |
| Amazon Connect DID | 1 DID per practice | $1.00 |
| Amazon Connect voice usage | 200 calls × 1.5 min × $0.008/min inbound | $2.40 |
| Claude Sonnet (Bedrock) | ~3 turns × ~2K tokens × 200 calls; $3/M input, $15/M output | $3.60 |
| Lambda compute | Code-hook + router, ~200 invocations | $0.10 |
| DynamoDB | On-demand, minimal R/W | $0.25 |
| **Baseline total** | | **~$7.35** |

## Optional Add-On — Contact Lens

Contact Lens analytics (real-time transcription, sentiment, post-call summaries) is a P1 item in the hardening plan, not part of the pilot baseline.

| Component | Assumption | Cost |
| --- | --- | --- |
| Contact Lens | 200 calls × 1.5 min × $0.015/min | $4.50 |
| **With Contact Lens total** | | **~$11.85** (≈ $12) |

## At Scale — 20,000 Practices

| Metric | Baseline | With Contact Lens |
| --- | --- | --- |
| Monthly infrastructure cost | ~$147,000 | ~$240,000 |
| Per-call cost | ~$0.04 | ~$0.06 |
| Calls handled per month | 4,000,000 | 4,000,000 |

## Break-Even vs Staff Cost

A front-desk staff member at $20/hour spends an estimated 5–8 hours per month on patient verification calls (60–90 seconds × 200 calls). That's $100–$150 per practice per month in displaced staff time.

| Configuration | Cost | Displaced staff time | Net |
| --- | --- | --- | --- |
| Baseline | $7.35 | $100–$150 | $93–$143 saved |
| With Contact Lens | $11.85 | $100–$150 | $88–$138 saved |

The 5–8 hours/month figure is an estimate based on call duration and volume. It needs validation from a real pilot before being quoted to leadership or used in business-case math.

## What This Does Not Include

- One-time onboarding labor per practice (clinician completes SMART-on-FHIR consent)
- KMS key usage and CloudTrail (negligible at pilot scale; tracked separately at scale)
- WAF + API Gateway (Phase 1.6 of the hardening plan; ~$5–$10/month/practice once added)
- Multi-region DR (Phase 4; not in pilot)
- ElevenLabs TTS if substituted for Polly (P2 item)
