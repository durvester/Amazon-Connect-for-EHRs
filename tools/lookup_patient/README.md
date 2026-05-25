# tools/lookup_patient

Lambda tool the agent calls to search Practice Fusion FHIR for a matching patient.

**Inputs:** `phone` (any format), `dob` (YYYY-MM-DD), `practice_id`.
**Outputs:** structured result — `match` (single Patient) | `multiple_matches` (count) | `no_match`.

## Files

- `src/lookup_patient/handler.py` — Lambda entrypoint (Session 0003)
- `src/lookup_patient/fhir_client.py` — HTTP client for Practice Fusion FHIR (Session 0003)
- `src/lookup_patient/normalize.py` — input normalization (implemented in Session 0001 as the TDD seed)

## Tests

- `tests/test_normalize.py` — phone E.164 normalization (real coverage, ships with the bootstrap)
- `tests/test_fhir_client.py` — mocked-PF tests (Session 0003)
- `tests/test_handler.py` — Lambda integration tests (Session 0003)
- `tests/fixtures/*.json` — recorded FHIR Bundle responses

Integration tests are marked `@pytest.mark.integration` and skip without the `PF_*` env vars (see `docs/credentials.md`).
