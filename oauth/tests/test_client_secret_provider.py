"""Tests for the PF client-secret resolver."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from oauth.client_secret_provider import ClientSecretError, resolve


@mock_aws
def test_resolve_returns_secret_string():
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    arn = sm.create_secret(Name="pf-voice-qa/practice/pf-001/pf_client_secret",
                           SecretString="sekret")["ARN"]
    assert resolve(arn, region="us-east-1") == "sekret"


@mock_aws
def test_resolve_missing_secret_raises():
    with pytest.raises(ClientSecretError):
        resolve("arn:aws:secretsmanager:us-east-1:1:secret:nope-AbCdEf",
                region="us-east-1")
