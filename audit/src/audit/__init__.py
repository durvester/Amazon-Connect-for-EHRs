"""HIPAA accounting-of-disclosures (`disclosure_log`) and rate limit
(`rate_limit`).

Both are env-var configured; CDK passes the actual resource names in
via the Lambda environment (per ADR-0008). Tests inject the same
shape via `monkeypatch.setenv`.
"""
