"""Per-(practice, ANI) rate limit backed by DDB ConditionalUpdate.

The table is created by infra/lib/rate-limit-stack.ts. Schema:
  PK   pk        S    "practice_id#ani"
  SK   bucket    S    "YYYY-MM-DD"  (daily buckets)
  attr count     N
  attr expires   N    epoch seconds  (TTL attribute, ~48 h after bucket date)

Over-budget surfaces as RateLimitExceeded; lookup_patient turns this
into match: "rate_limited" (ADR-0009 — leak-resistance).
"""

from __future__ import annotations

from datetime import date

import boto3
import pytest
from moto import mock_aws

TABLE = "pf-voice-qa-rate-limit"


@pytest.fixture
def rate_table(monkeypatch):
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "bucket", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "bucket", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("RATELIMIT_TABLE_NAME", TABLE)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        yield ddb


def test_first_call_creates_row_at_count_one(rate_table):
    from audit.rate_limit import check_and_increment

    n = check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=5)
    assert n == 1


def test_increments_within_budget(rate_table):
    from audit.rate_limit import check_and_increment

    for expected in range(1, 6):
        n = check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=5)
        assert n == expected


def test_over_budget_raises_and_does_not_increment(rate_table):
    from audit.rate_limit import RateLimitExceeded, check_and_increment

    for _ in range(5):
        check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=5)

    with pytest.raises(RateLimitExceeded):
        check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=5)

    # The failed attempt must not have incremented — verify by trying again
    # with a higher cap and confirming the counter is still 5 (next call → 6).
    n = check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=10)
    assert n == 6


def test_separate_practice_or_ani_independent_buckets(rate_table):
    from audit.rate_limit import check_and_increment

    n1 = check_and_increment(practice_id="pf-001", ani="+1A", max_per_day=2)
    n2 = check_and_increment(practice_id="pf-001", ani="+1B", max_per_day=2)
    n3 = check_and_increment(practice_id="pf-002", ani="+1A", max_per_day=2)
    assert (n1, n2, n3) == (1, 1, 1)


def test_raises_when_table_env_missing(monkeypatch):
    from audit.rate_limit import RateLimitConfigError, check_and_increment

    monkeypatch.delenv("RATELIMIT_TABLE_NAME", raising=False)
    with pytest.raises(RateLimitConfigError):
        check_and_increment(practice_id="pf-001", ani="+17163619276", max_per_day=1)


def test_today_bucket_key_format(rate_table):
    """The bucket attribute is today's date in ISO format."""
    from audit.rate_limit import _today_bucket

    assert _today_bucket() == date.today().isoformat()
