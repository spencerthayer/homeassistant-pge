"""Print live PGE GraphQL type field names. No tokens or account values."""

import asyncio
from pathlib import Path

import aiohttp

from custom_components.pge_energy.api_host import graphql_url
from custom_components.pge_energy.billing_api import (
    GET_NET_METERING_DETAILS,
    GET_RATE_COMPARE,
)
from custom_components.pge_energy.const import PGE_PORTAL_ORIGIN, PGE_PORTAL_REFERER
from custom_components.pge_energy.portal_auth import async_login_or_refresh

ROOT = Path(__file__).resolve().parents[1]

QUERY = ""


def _env() -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip("\"'")
    return parsed


def _names_only(payload: dict) -> dict:
    data = payload.get("data") or {}
    out: dict = {"errors": []}
    for err in payload.get("errors") or []:
        if isinstance(err, dict):
            out["errors"].append(str(err.get("message") or "")[:300])
    for key in ("net", "rate"):
        node = data.get(key) or {}
        fields = node.get("fields") if isinstance(node, dict) else None
        out[key] = sorted(field.get("name") for field in fields or [] if isinstance(field, dict) and field.get("name"))
    wanted = ("net", "rate", "meter", "compare")
    matches = []
    fields = ((data.get("schema") or {}).get("queryType") or {}).get("fields") or []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        if any(token in name.lower() for token in wanted):
            matches.append({"name": name, "type": field.get("type")})
    out["root"] = matches
    return out


async def main() -> None:
    env = _env()
    result = await async_login_or_refresh(
        email=env["email"],
        password=env["password"],
        refresh_credential=None,
    )
    headers = {
        "authorization": f"Bearer {result.access_token}",
        "content-type": "application/json",
        "aws_graphql_server": "graphql_server",
        "origin": PGE_PORTAL_ORIGIN,
        "referer": PGE_PORTAL_REFERER,
    }
    probes = (
        (
            "getNetMeteringDetails",
            GET_NET_METERING_DETAILS,
            {"params": {"encryptedAccountId": "x", "encryptedPremiseId": "y"}},
        ),
        ("getRateCompare", GET_RATE_COMPARE, {"params": {"accountNumber": "x"}}),
        (
            "typename-only",
            "query Q($params: NetMeteringDetailsParams!) { getNetMeteringDetails(params: $params) { __typename } }",
            {"params": {"encryptedAccountId": "x", "encryptedPremiseId": "y"}},
        ),
    )
    async with aiohttp.ClientSession() as session:
        for name, query, variables in probes:
            async with session.post(
                graphql_url(),
                json={"query": query, "variables": variables, "operationName": name},
                headers=headers,
            ) as resp:
                payload = await resp.json(content_type=None)
                messages = []
                if isinstance(payload, dict):
                    for err in payload.get("errors") or []:
                        if isinstance(err, dict):
                            messages.append(str(err.get("message") or "")[:500])
                    if payload.get("data"):
                        messages.append("data-keys=" + ",".join(payload["data"].keys()))
                print(name, resp.status, messages)


if __name__ == "__main__":
    asyncio.run(main())
