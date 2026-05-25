"""DynamoDB-backed cache for the in-flight OAuth state (Session 0008).

The SMART authorization-code flow generates a fresh `state` + PKCE pair
on /oauth/start, then waits — possibly minutes — for the practice to
return through /oauth/callback. We have to remember which practice the
flow was for, the PKCE verifier (so the token exchange can prove it),
the discovered SMART endpoints, and the PF Provider App client id +
secret pointer (so multi-tenancy stays data-driven from end to end).

A DDB table keyed on `state` is the simplest fit:
- single-region, single-digit-ms latency, no extra infra
- TTL attribute auto-evicts abandoned flows (no janitor cron)
- conditional writes prevent the (admittedly improbable) state collision
- `consume` is implemented as a conditional delete that returns the
  prior item — atomic single-use semantics with no race window

Schema:
    state (PK)                : S
    practice_id               : S
    code_verifier             : S
    fhir_base_url             : S
    token_endpoint            : S
    pf_client_id              : S
    pf_client_secret_arn      : S
    ttl                       : N  (epoch seconds — DDB TTL attribute)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError


class OAuthStateStoreError(RuntimeError):
    """Base for state-store failures (bad input, DDB error, malformed row)."""


class OAuthStateAlreadyExists(OAuthStateStoreError):
    """Raised when ``put`` collides with an existing un-consumed state."""


@dataclass(frozen=True)
class OAuthStatePayload:
    state: str
    practice_id: str
    code_verifier: str
    fhir_base_url: str
    token_endpoint: str
    pf_client_id: str
    pf_client_secret_arn: str
    ttl: int


class OAuthStateStore:
    def __init__(self, *, table_name: str, region: str = "us-east-1"):
        self._table_name = table_name
        self._ddb = boto3.client("dynamodb", region_name=region)

    def put(
        self,
        *,
        state: str,
        practice_id: str,
        code_verifier: str,
        fhir_base_url: str,
        token_endpoint: str,
        pf_client_id: str,
        pf_client_secret_arn: str,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise OAuthStateStoreError("ttl_seconds must be positive")
        ttl = int(time.time()) + int(ttl_seconds)
        try:
            self._ddb.put_item(
                TableName=self._table_name,
                Item={
                    "state": {"S": state},
                    "practice_id": {"S": practice_id},
                    "code_verifier": {"S": code_verifier},
                    "fhir_base_url": {"S": fhir_base_url},
                    "token_endpoint": {"S": token_endpoint},
                    "pf_client_id": {"S": pf_client_id},
                    "pf_client_secret_arn": {"S": pf_client_secret_arn},
                    "ttl": {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(#s)",
                ExpressionAttributeNames={"#s": "state"},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise OAuthStateAlreadyExists(
                    f"state {state!r} already in flight"
                ) from e
            raise OAuthStateStoreError(f"DDB put failed: {e}") from e

    def get(self, state: str) -> OAuthStatePayload | None:
        try:
            resp = self._ddb.get_item(
                TableName=self._table_name,
                Key={"state": {"S": state}},
            )
        except ClientError as e:
            raise OAuthStateStoreError(f"DDB get failed: {e}") from e
        item = resp.get("Item")
        if not item:
            return None
        return _item_to_payload(item)

    def consume(self, state: str) -> OAuthStatePayload | None:
        """Atomic single-use: delete + return the prior item, or None if
        no row was present. Replays of the same state after a successful
        consume return None."""
        try:
            resp = self._ddb.delete_item(
                TableName=self._table_name,
                Key={"state": {"S": state}},
                ReturnValues="ALL_OLD",
            )
        except ClientError as e:
            raise OAuthStateStoreError(f"DDB delete failed: {e}") from e
        item = resp.get("Attributes")
        if not item:
            return None
        return _item_to_payload(item)


def _item_to_payload(item: dict) -> OAuthStatePayload:
    try:
        return OAuthStatePayload(
            state=item["state"]["S"],
            practice_id=item["practice_id"]["S"],
            code_verifier=item["code_verifier"]["S"],
            fhir_base_url=item["fhir_base_url"]["S"],
            token_endpoint=item["token_endpoint"]["S"],
            pf_client_id=item["pf_client_id"]["S"],
            pf_client_secret_arn=item["pf_client_secret_arn"]["S"],
            ttl=int(item["ttl"]["N"]),
        )
    except KeyError as e:
        raise OAuthStateStoreError(f"oauth-state row missing field {e}") from e
