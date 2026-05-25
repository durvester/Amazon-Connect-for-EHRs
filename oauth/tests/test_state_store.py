"""Tests for the DDB-backed OAuth state cache (Session 0008).

The state store bridges /oauth/start (writes a PKCE pair + practice
metadata) and /oauth/callback (reads + consumes the same row). It must:

- round-trip every onboarding field intact
- enforce single-use semantics (`consume` returns the payload exactly
  once, then `get` returns None)
- set a TTL attribute so abandoned rows expire automatically
- reject collisions on the same `state` value
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from oauth.state_store import (
    OAuthStateStore,
    OAuthStatePayload,
    OAuthStateAlreadyExists,
    OAuthStateStoreError,
)

TABLE = "oauth-state-test"


def _bootstrap_ddb():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "state", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "state", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


def _put(store: OAuthStateStore, state="s-1"):
    store.put(
        state=state,
        practice_id="pf-001",
        code_verifier="v" * 64,
        fhir_base_url="https://qa.example.com/fhir/r4",
        token_endpoint="https://qa.example.com/oauth/v1/token",
        pf_client_id="cid",
        pf_client_secret_arn="arn:aws:secretsmanager:us-east-1:0:secret:x",
        ttl_seconds=600,
    )


@mock_aws
def test_put_and_get_round_trip():
    _bootstrap_ddb()
    store = OAuthStateStore(table_name=TABLE)
    _put(store)
    payload = store.get("s-1")
    assert isinstance(payload, OAuthStatePayload)
    assert payload.practice_id == "pf-001"
    assert payload.code_verifier == "v" * 64
    assert payload.fhir_base_url == "https://qa.example.com/fhir/r4"
    assert payload.token_endpoint == "https://qa.example.com/oauth/v1/token"
    assert payload.pf_client_id == "cid"
    assert payload.pf_client_secret_arn.startswith("arn:aws:secretsmanager:")


@mock_aws
def test_get_missing_returns_none():
    _bootstrap_ddb()
    store = OAuthStateStore(table_name=TABLE)
    assert store.get("nope") is None


@mock_aws
def test_consume_is_single_use():
    _bootstrap_ddb()
    store = OAuthStateStore(table_name=TABLE)
    _put(store, state="s-2")
    payload = store.consume("s-2")
    assert payload is not None
    assert payload.practice_id == "pf-001"
    assert store.get("s-2") is None
    assert store.consume("s-2") is None


@mock_aws
def test_put_rejects_duplicate_state():
    _bootstrap_ddb()
    store = OAuthStateStore(table_name=TABLE)
    _put(store, state="s-3")
    with pytest.raises(OAuthStateAlreadyExists):
        _put(store, state="s-3")


@mock_aws
def test_put_writes_ttl_attribute():
    _bootstrap_ddb()
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    store = OAuthStateStore(table_name=TABLE)
    _put(store, state="s-4")
    item = ddb.get_item(TableName=TABLE, Key={"state": {"S": "s-4"}})["Item"]
    assert "ttl" in item
    assert int(item["ttl"]["N"]) > 0


@mock_aws
def test_put_validates_ttl():
    _bootstrap_ddb()
    store = OAuthStateStore(table_name=TABLE)
    with pytest.raises(OAuthStateStoreError):
        store.put(
            state="s-5",
            practice_id="pf-001",
            code_verifier="v" * 64,
            fhir_base_url="x",
            token_endpoint="x",
            pf_client_id="x",
            pf_client_secret_arn="x",
            ttl_seconds=0,
        )
