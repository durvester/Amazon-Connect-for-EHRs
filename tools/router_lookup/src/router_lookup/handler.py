"""Router Lambda: DID -> pf_org_uuid (ADR-0014, ADR-0018, ADR-0020).

Invoked by the Connect contact flow via InvokeLambdaFunction (8s max).
Reads the phone_routing DDB table and returns a STRING_MAP with
pf_org_uuid. Connect sets this as a contact attribute before handing
off to the Lex bot.
"""

from __future__ import annotations

import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ddb = None


def _get_ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def handler(event: dict, context: object) -> dict[str, str]:
    table = os.environ["PF_PHONE_ROUTING_TABLE"]
    did = event["Details"]["ContactData"]["SystemEndpoint"]["Address"]

    resp = _get_ddb().get_item(
        TableName=table,
        Key={"phone_number": {"S": did}},
    )

    item = resp.get("Item")
    if item and item.get("status", {}).get("S") == "active":
        pf_org_uuid = item["pf_org_uuid"]["S"]
        logger.info("router resolved DID=%s to pf_org_uuid=%s", did, pf_org_uuid)
        return {"pf_org_uuid": pf_org_uuid}

    logger.warning("router: no active mapping for DID=%s", did)
    return {"pf_org_uuid": "UNKNOWN"}
