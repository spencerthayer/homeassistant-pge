#!/usr/bin/env python3
"""Enable bill PDF line-item entities for Lovelace UAT on the live HA instance."""

from __future__ import annotations

import asyncio

import aiohttp

BASE = "http://127.0.0.1:8123"
WS = "ws://127.0.0.1:8123/api/websocket"


async def _token(session: aiohttp.ClientSession) -> str:
    async with session.post(
        f"{BASE}/auth/login_flow",
        json={
            "client_id": f"{BASE}/",
            "handler": ["homeassistant", None],
            "redirect_uri": f"{BASE}/",
        },
    ) as resp:
        flow = await resp.json()
    flow_id = flow["flow_id"]
    async with session.post(
        f"{BASE}/auth/login_flow/{flow_id}",
        json={"client_id": f"{BASE}/", "username": "dev", "password": "devpass"},
    ) as resp:
        result = await resp.json()
    async with session.post(
        f"{BASE}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": result["result"],
            "client_id": f"{BASE}/",
        },
    ) as resp:
        return (await resp.json())["access_token"]


async def _ws_req(ws: aiohttp.ClientWebSocketResponse, msg_id: int, payload: dict) -> dict:
    await ws.send_json({**payload, "id": msg_id})
    while True:
        msg = await ws.receive_json()
        if msg.get("id") == msg_id:
            return msg


async def main() -> int:
    async with aiohttp.ClientSession() as session:
        token = await _token(session)
        async with session.ws_connect(WS) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            assert (await ws.receive_json()).get("type") == "auth_ok"

            listed = await _ws_req(ws, 1, {"type": "config/entity_registry/list"})
            ents = [
                e
                for e in listed["result"]
                if "bill_pdf_" in e.get("entity_id", "") and not e["entity_id"].endswith("_bill_pdf_parse_status")
            ]
            print(f"found {len(ents)} bill_pdf line-item entities")
            enabled: list[str] = []
            msg_id = 1
            for entry in ents:
                msg_id += 1
                resp = await _ws_req(
                    ws,
                    msg_id,
                    {
                        "type": "config/entity_registry/update",
                        "entity_id": entry["entity_id"],
                        "disabled_by": None,
                    },
                )
                status = "OK" if resp.get("success") else "FAIL"
                print(status, entry["entity_id"], resp.get("error") or "")
                if resp.get("success"):
                    enabled.append(entry["entity_id"])

        await asyncio.sleep(4)
        headers = {"Authorization": f"Bearer {token}"}
        print("--- states ---")
        for entity_id in sorted(enabled):
            async with session.get(f"{BASE}/api/states/{entity_id}", headers=headers) as resp:
                if resp.status != 200:
                    print(entity_id, "HTTP", resp.status)
                    continue
                state = await resp.json()
                unit = state.get("attributes", {}).get("unit_of_measurement") or ""
                print(f"{entity_id}: {state.get('state')} {unit}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
