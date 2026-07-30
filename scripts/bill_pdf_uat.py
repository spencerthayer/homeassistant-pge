#!/usr/bin/env python3
"""Live bill PDF UAT helper — enable options, download, verify."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

ENTRY_ID = "01KY89CYSD3G0B24HNNH9R60PS"
BASE = "http://127.0.0.1:8123"
WS = "ws://127.0.0.1:8123/api/websocket"
REPO = Path(__file__).resolve().parents[1]
STORE = Path(
    "/Users/spencerthayer/Work/_Personal/PGE_Data_Scrape/outputs/ha_live/20260723T200252Z/config/.storage/pge_energy.import_state.01KY89CYSD3G0B24HNNH9R60PS"
)
WWW = Path(
    "/Users/spencerthayer/Work/_Personal/PGE_Data_Scrape/outputs/ha_live/20260723T200252Z/config/www/pge_energy"
)
LOG = REPO / "outputs/ha_live/hass.log"


async def get_token(session: aiohttp.ClientSession) -> str:
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


async def ws_call(ws: aiohttp.ClientWebSocketResponse, msg_id: int, payload: dict) -> dict:
    payload = {**payload, "id": msg_id}
    await ws.send_json(payload)
    while True:
        msg = await ws.receive_json()
        if msg.get("id") == msg_id:
            return msg


async def main() -> int:
    bill_date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-13"
    async with aiohttp.ClientSession() as session:
        token = await get_token(session)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with session.post(
            f"{BASE}/api/services/pge_energy/download_bill_pdf",
            headers=headers,
            json={"entry_id": ENTRY_ID, "bill_date": bill_date},
        ) as resp:
            body = await resp.text()
            print("download_bill_pdf:", resp.status, body[:200])

    for _ in range(60):
        data = json.loads(STORE.read_text())["data"]
        entry = (data.get("bill_pdf_index") or {}).get(bill_date, {})
        files = entry.get("files") or {}
        detailed = files.get("detailed")
        if detailed:
            print("file:", detailed.get("relpath"), detailed.get("size_bytes"), "bytes")
            norm = (entry.get("normalized") or {}).get("detailed") or {}
            print("parse:", norm.get("status"), "amount:", norm.get("amount_due"), "kwh:", norm.get("total_kwh"))
            attempts = (entry.get("parse_attempts") or {}).get("detailed") or {}
            print("attempt status:", attempts.get("status"))
            break
        await asyncio.sleep(2)
    else:
        print("timeout waiting for PDF file metadata")
        return 1

    pdfs = list(WWW.rglob("*.pdf")) if WWW.exists() else []
    print("pdf on disk:", len(pdfs))
    for p in pdfs[:5]:
        print(" ", p)

    if LOG.exists():
        for line in LOG.read_text(errors="replace").splitlines():
            if "Bill PDF" in line or "bill_pdf" in line.lower():
                last = line
        else:
            last = None
        if last:
            print("last pdf log:", last[-200:])

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
