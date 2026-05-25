"""Per-(practice, ANI) daily rate limit, DDB-backed.

One row per (practice_id#ani, YYYY-MM-DD) day-bucket. Single DDB
ConditionalUpdate per check: atomic increment + budget gate. Rows
auto-expire ~48 h after their bucket date via the table's TTL
attribute.

Over-budget surfaces as ``RateLimitExceeded``; ``lookup_patient`` maps
this to ``match: "rate_limited"`` so the agent's response to a real
caller cannot be used to distinguish "lookup attempted and over
budget" from "lookup not attempted at all" (leak-resistance —
ADR-0009).

Configuration (Lambda env vars; CDK injects):
  RATELIMIT_TABLE_NAME   required
"""

from __future__ import annotations

import os
import time
from datetime import date

import boto3
from botocore.exceptions import ClientError

_TTL_SECONDS_AFTER_BUCKET = 48 * 3600


class RateLimitConfigError(RuntimeError):
    """Required configuration missing."""


class RateLimitExceeded(RuntimeError):
    """Budget exhausted for the current bucket."""


def _today_bucket() -> str:
    return date.today().isoformat()


def check_and_increment(
    *,
    practice_id: str,
    ani: str,
    max_per_day: int,
) -> int:
    """Atomically increment the (practice_id, ani, today) counter if under
    budget; otherwise raise ``RateLimitExceeded``. Returns the new count.

    Uses a single DDB UpdateItem with a ConditionExpression that compares
    the existing count against ``max_per_day`` (or treats a missing row
    as count==0). Concurrent calls are linearized by DDB.
    """
    table_name = os.environ.get("RATELIMIT_TABLE_NAME")
    if not table_name:
        raise RateLimitConfigError("RATELIMIT_TABLE_NAME env var not set")

    ddb = boto3.client("dynamodb")
    pk = f"{practice_id}#{ani}"
    bucket = _today_bucket()
    expires = int(time.time()) + _TTL_SECONDS_AFTER_BUCKET

    try:
        resp = ddb.update_item(
            TableName=table_name,
            Key={"pk": {"S": pk}, "bucket": {"S": bucket}},
            UpdateExpression="SET #c = if_not_exists(#c, :zero) + :one, #e = :exp",
            ConditionExpression="attribute_not_exists(#c) OR #c < :cap",
            ExpressionAttributeNames={"#c": "count", "#e": "expires"},
            ExpressionAttributeValues={
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":cap": {"N": str(max_per_day)},
                ":exp": {"N": str(expires)},
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise RateLimitExceeded(
                f"budget {max_per_day}/day exhausted for {pk} on {bucket}"
            ) from e
        raise

    return int(resp["Attributes"]["count"]["N"])
