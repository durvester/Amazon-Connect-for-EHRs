"""Per-practice configuration store (DynamoDB).

One row per practice. Holds the small set of fields the *read* path
needs at every FHIR call:

  practice_id (PK)         : S
  fhir_base_url            : S
  token_endpoint           : S    (cached from SMART discovery at onboarding)
  pf_client_id             : S    (OK to store plaintext — not a secret)
  pf_client_secret_arn     : S    (pointer into Secrets Manager)

The full `practices` table schema (architecture.md) has more fields
(`verification_factors`, `connect_queue_arn`, business hours…) that the
*agent* layer cares about. Sessions 0010+ extend this store; today's
read path only needs the OAuth-adjacent subset.

Writes are owned by the OAuth onboarding API (Session 0008). This
module is read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError


class PracticesStoreError(RuntimeError):
    """Raised on any DDB error, missing row, or malformed item."""


@dataclass(frozen=True)
class PracticeRecord:
    practice_id: str
    fhir_base_url: str
    token_endpoint: str
    pf_client_id: str
    pf_client_secret_arn: str
    business_hours: dict | None = None


class PracticesStore:
    def __init__(self, *, table_name: str, region: str = "us-east-1"):
        self._table_name = table_name
        self._ddb = boto3.client("dynamodb", region_name=region)

    def get(self, practice_id: str) -> PracticeRecord:
        """Return the practice's OAuth-adjacent config. Raises if missing —
        a call for a practice we don't know about is a configuration bug,
        not a normal "not found"."""
        try:
            resp = self._ddb.get_item(
                TableName=self._table_name,
                Key={"practice_id": {"S": practice_id}},
            )
        except ClientError as e:
            raise PracticesStoreError(f"DDB get failed: {e}") from e

        item = resp.get("Item")
        if not item:
            raise PracticesStoreError(f"no practices row for {practice_id!r}")

        try:
            bh_raw = item.get("business_hours", {}).get("S")
            business_hours = None
            if bh_raw:
                import json
                try:
                    business_hours = json.loads(bh_raw)
                except (json.JSONDecodeError, TypeError):
                    pass

            return PracticeRecord(
                practice_id=item["practice_id"]["S"],
                fhir_base_url=item["fhir_base_url"]["S"],
                token_endpoint=item["token_endpoint"]["S"],
                pf_client_id=item["pf_client_id"]["S"],
                pf_client_secret_arn=item["pf_client_secret_arn"]["S"],
                business_hours=business_hours,
            )
        except KeyError as e:
            raise PracticesStoreError(
                f"practices row {practice_id!r} missing field {e}"
            ) from e

    def put(
        self,
        *,
        practice_id: str,
        fhir_base_url: str,
        token_endpoint: str,
        pf_client_id: str,
        pf_client_secret_arn: str,
    ) -> None:
        """Upsert the OAuth-adjacent config for a practice.

        Written by the OAuth onboarding API (Session 0008) on a successful
        /oauth/callback. Idempotent — re-onboarding a practice overwrites
        the same fields with the same values.
        """
        try:
            self._ddb.put_item(
                TableName=self._table_name,
                Item={
                    "practice_id": {"S": practice_id},
                    "fhir_base_url": {"S": fhir_base_url},
                    "token_endpoint": {"S": token_endpoint},
                    "pf_client_id": {"S": pf_client_id},
                    "pf_client_secret_arn": {"S": pf_client_secret_arn},
                },
            )
        except ClientError as e:
            raise PracticesStoreError(f"DDB put failed: {e}") from e
