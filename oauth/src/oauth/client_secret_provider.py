"""Resolve a Secrets Manager ARN to the plaintext PF client secret.

Used by the refresh flow: the practices_store row holds an ARN (a
pointer), not the secret itself. This module's `resolve()` fetches the
plaintext via Secrets Manager GetSecretValue.

Caching is intentionally not done here. Lambda's execution-context
reuse already caches by virtue of the boto3 client surviving warm
invocations; adding our own cache would create staleness on rotation.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError


class ClientSecretError(RuntimeError):
    """Raised on Secrets Manager errors or malformed secret payloads."""


def resolve(secret_arn: str, *, region: str = "us-east-1") -> str:
    """Return the plaintext PF client secret stored at ``secret_arn``."""
    sm = boto3.client("secretsmanager", region_name=region)
    try:
        resp = sm.get_secret_value(SecretId=secret_arn)
    except ClientError as e:
        raise ClientSecretError(f"GetSecretValue failed for {secret_arn}: {e}") from e

    if "SecretString" in resp:
        return resp["SecretString"]
    raise ClientSecretError(f"secret {secret_arn} has no SecretString payload")
