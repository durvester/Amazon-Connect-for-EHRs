"""Tests for the per-practice config store."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from oauth.practices_store import PracticeRecord, PracticesStore, PracticesStoreError

TABLE = "practices-test"


def _bootstrap_ddb():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "practice_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "practice_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


def _seed(ddb, practice_id="pf-001"):
    ddb.put_item(
        TableName=TABLE,
        Item={
            "practice_id": {"S": practice_id},
            "fhir_base_url": {"S": "https://qa-api.practicefusion.com/fhir/r4/v1/org-x"},
            "token_endpoint": {"S": "https://qa-api.practicefusion.com/fhir/r4/v1/org-x/token"},
            "pf_client_id": {"S": "client-abc"},
            "pf_client_secret_arn": {"S": "arn:aws:secretsmanager:us-east-1:1:secret:x"},
        },
    )


@mock_aws
def test_get_returns_record():
    ddb = _bootstrap_ddb()
    _seed(ddb)

    rec = PracticesStore(table_name=TABLE, region="us-east-1").get("pf-001")
    assert isinstance(rec, PracticeRecord)
    assert rec.practice_id == "pf-001"
    assert rec.fhir_base_url.endswith("/org-x")
    assert rec.token_endpoint.endswith("/org-x/token")
    assert rec.pf_client_id == "client-abc"
    assert rec.pf_client_secret_arn.startswith("arn:")


@mock_aws
def test_get_missing_raises():
    _bootstrap_ddb()

    with pytest.raises(PracticesStoreError, match="no practices row"):
        PracticesStore(table_name=TABLE, region="us-east-1").get("pf-missing")


@mock_aws
def test_put_writes_and_get_round_trips():
    _bootstrap_ddb()
    store = PracticesStore(table_name=TABLE, region="us-east-1")
    store.put(
        practice_id="pf-new",
        fhir_base_url="https://qa.example.com/fhir/r4",
        token_endpoint="https://qa.example.com/oauth/v1/token",
        pf_client_id="cid-new",
        pf_client_secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:y",
    )
    rec = store.get("pf-new")
    assert rec.practice_id == "pf-new"
    assert rec.pf_client_id == "cid-new"


@mock_aws
def test_put_is_idempotent_overwrite():
    _bootstrap_ddb()
    store = PracticesStore(table_name=TABLE, region="us-east-1")
    common = dict(
        practice_id="pf-iio",
        fhir_base_url="https://a",
        token_endpoint="https://b",
        pf_client_id="c",
        pf_client_secret_arn="arn:1",
    )
    store.put(**common)
    store.put(**{**common, "pf_client_id": "c2"})
    rec = store.get("pf-iio")
    assert rec.pf_client_id == "c2"


@mock_aws
def test_malformed_row_raises():
    ddb = _bootstrap_ddb()
    ddb.put_item(
        TableName=TABLE,
        Item={"practice_id": {"S": "pf-bad"}},  # missing every other field
    )

    with pytest.raises(PracticesStoreError, match="missing field"):
        PracticesStore(table_name=TABLE, region="us-east-1").get("pf-bad")
