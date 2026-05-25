"""Tests for the router_lookup Lambda handler (ADR-0020: pf_org_uuid).

The router Lambda is invoked by the Connect contact flow via
InvokeLambdaFunction. It receives the contact event, extracts
$.SystemEndpoint.Address (the called DID), looks up the phone_routing
table, and returns {pf_org_uuid} as a STRING_MAP so Connect can set
it as a contact attribute.
"""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws


TABLE_NAME = "pf-voice-qa-phone-routing"


def _make_connect_event(system_endpoint: str = "+15551234567") -> dict:
    return {
        "Details": {
            "ContactData": {
                "Attributes": {},
                "Channel": "VOICE",
                "ContactId": "abc-123",
                "CustomerEndpoint": {"Address": "+15559876543", "Type": "TELEPHONE_NUMBER"},
                "SystemEndpoint": {"Address": system_endpoint, "Type": "TELEPHONE_NUMBER"},
                "InstanceARN": "arn:aws:connect:us-east-1:123456789012:instance/test",
            },
            "Parameters": {},
        },
        "Name": "ContactFlowEvent",
    }


def _seed_phone_routing(ddb, phone: str, pf_org_uuid: str, status: str = "active") -> None:
    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "phone_number": {"S": phone},
            "pf_org_uuid": {"S": pf_org_uuid},
            "connect_instance_id": {"S": "inst-1"},
            "claimed_at": {"S": "2026-05-24T00:00:00+00:00"},
            "status": {"S": status},
        },
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PF_PHONE_ROUTING_TABLE", TABLE_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@mock_aws
def test_returns_pf_org_uuid_for_active_did():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "phone_number", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "phone_number", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _seed_phone_routing(ddb, "+15551234567", "b4ab304f-d1ac-4565-8dca-992b589422a7")

    from router_lookup.handler import handler

    result = handler(_make_connect_event("+15551234567"), {})
    assert result["pf_org_uuid"] == "b4ab304f-d1ac-4565-8dca-992b589422a7"


@mock_aws
def test_returns_unknown_for_missing_did():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "phone_number", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "phone_number", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    from router_lookup.handler import handler

    result = handler(_make_connect_event("+15559999999"), {})
    assert result["pf_org_uuid"] == "UNKNOWN"


@mock_aws
def test_returns_unknown_for_released_did():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "phone_number", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "phone_number", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _seed_phone_routing(ddb, "+15551234567", "b4ab304f-d1ac-4565-8dca-992b589422a7", status="released")

    from router_lookup.handler import handler

    result = handler(_make_connect_event("+15551234567"), {})
    assert result["pf_org_uuid"] == "UNKNOWN"


@mock_aws
def test_returns_string_map_format():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "phone_number", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "phone_number", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _seed_phone_routing(ddb, "+15551234567", "b4ab304f-d1ac-4565-8dca-992b589422a7")

    from router_lookup.handler import handler

    result = handler(_make_connect_event("+15551234567"), {})
    assert isinstance(result, dict)
    for k, v in result.items():
        assert isinstance(k, str)
        assert isinstance(v, str)
