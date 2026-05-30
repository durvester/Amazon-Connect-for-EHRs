# scripts/

Developer utilities for exploring and testing FHIR integrations. Not deployed.

- `probe-fhir-resources.py` — Probe a FHIR server for clinical resources of a known patient. Uses the same credential chain (DDB + KMS) as the live Lambdas. Requires `PF_ORG_UUID` and `PATIENT_ID` env vars.
