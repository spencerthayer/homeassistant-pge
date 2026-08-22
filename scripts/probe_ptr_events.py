"""Probe live PGE GraphQL for Peak Time Events data.

Usage:
  .venv/bin/python scripts/probe_ptr_events.py

Reads PGE_EMAIL / PGE_PASSWORD from environment or prompts.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

# Add repo root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.pge_energy import portal_auth
from custom_components.pge_energy.auth import PGEAuthManager, generate_immutable_account_key
from custom_components.pge_energy.billing_api import (
    GET_PEAK_TIME_REBATE_ENROLLMENT_DETAILS,
    PGEBillingApiClient,
)

GRAPHQL_URL = "https://apix.portlandgeneral.com/pge-graphql"
ORIGIN = "https://portlandgeneral.com"
REFERER = "https://portlandgeneral.com/"
TIMEOUT = aiohttp.ClientTimeout(total=30)


async def main() -> None:
    email = os.environ.get("PGE_EMAIL") or input("PGE_EMAIL: ").strip()
    password = os.environ.get("PGE_PASSWORD") or input("PGE_PASSWORD: ").strip()
    account_number = os.environ.get("PGE_ACCOUNT_NUMBER") or os.environ.get("PGE_ACCOUNT_ID")

    print(f"Logging in as {email}...")
    async with aiohttp.ClientSession() as session:
        # Authenticate
        result = await portal_auth.async_login_or_refresh(
            email=email,
            password=password,
            refresh_credential=None,
        )
        print(f"Login OK. Accounts: {result.account_ids}")

        if not account_number and result.account_ids:
            account_number = result.account_ids[0]
        if not account_number:
            print("No account ID found")
            return

        auth = PGEAuthManager(
            token=result.access_token,
            encrypted_person_id=result.encrypted_person_id or "",
            account_id=account_number,
            account_key=generate_immutable_account_key(),
            email=email,
            password=password,
            refresh_credential=result.refresh_credential,
            auth_mode="credential",
            token_expires_at=result.expires_at,
        )

        # Get encrypted account number via billing client
        billing = PGEBillingApiClient(session, auth)
        detail = await billing.get_account_detail(account_number)
        enc_account = detail.encrypted_account_number
        enc_premise = detail.encrypted_premise_id
        enc_sa = detail.encrypted_sa_id
        print(f"Encrypted account: {enc_account[:12]}...")
        print(f"Encrypted premise: {enc_premise[:12]}...")
        print(f"Encrypted SA:      {enc_sa[:12]}...")

        # Now probe the PTR detail endpoint with various mock dates
        token = await auth.ensure_valid_token()
        headers = {
            "accept": "*/*",
            "authorization": f"Bearer {token}",
            "aws_graphql_server": "graphql_server",
            "content-type": "application/json",
            "origin": ORIGIN,
            "referer": REFERER,
        }

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        test_dates = ["", today]

        # Add some future dates
        for days_ahead in [1, 3, 7, 14, 30]:
            future = (datetime.now(UTC) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            test_dates.append(future)

        # Also try some dates in active PTR seasons (summer: Jun-Sep, winter: Nov-Feb)
        test_dates.extend(
            [
                "2026-06-15",  # Early summer
                "2026-08-15",  # Mid summer
                "2026-09-15",  # Late summer
                "2026-11-15",  # Early winter
            ]
        )

        print("\n" + "=" * 80)
        print("PROBING getPeakTimeRebateEnrollmentDetails")
        print("=" * 80)

        for mock_date in test_dates:
            params = {
                "encryptedAccountNumber": enc_account,
                "ptrMockServerDate": mock_date,
            }
            payload = {
                "query": GET_PEAK_TIME_REBATE_ENROLLMENT_DETAILS,
                "variables": {"params": params},
                "operationName": "getPeakTimeRebateEnrollmentDetails",
            }

            label = f'ptrMockServerDate="{mock_date}"' if mock_date else 'ptrMockServerDate=""'
            print(f"\n--- {label} ---")

            try:
                async with session.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers=headers,
                    timeout=TIMEOUT,
                ) as resp:
                    body = await resp.json()
                    data = (body.get("data") or {}).get("getPeakTimeRebateEnrollmentDetails") or {}

                    # Show key fields
                    events = data.get("peakTimeEvents") or []
                    print(f"  enrollmentStatus: {data.get('enrollmentStatus')}")
                    print(f"  activePTRSeason:  {data.get('activePTRSeason')}")
                    print(f"  totalEarnedCredit: {data.get('totalEarnedCredit')}")
                    print(f"  # peakTimeEvents: {len(events)}")

                    if events:
                        # Sort by date for readability
                        sorted_events = sorted(events, key=lambda e: e.get("eventDate", ""))
                        for ev in sorted_events:
                            date_str = ev.get("eventDate", "?")
                            credit = ev.get("eventEarnedCredit")
                            print(f"    {date_str}  credit=${credit}")

                        # Check if any events are in the future
                        now_date = datetime.now(UTC).strftime("%Y-%m-%d")
                        future_events = [e for e in events if e.get("eventDate", "") > now_date]
                        if future_events:
                            print(f"  *** FUTURE EVENTS FOUND: {len(future_events)} ***")
                            for ev in future_events:
                                print(f"      FUTURE: {ev.get('eventDate')}  credit=${ev.get('eventEarnedCredit')}")
                    else:
                        print("  (no events)")

                    if data.get("seasonalDates"):
                        print(f"  seasonalDates: {json.dumps(data['seasonalDates'])}")
                    if data.get("lastPTRSeason"):
                        print(f"  lastPTRSeason: {data['lastPTRSeason']}")
                    if data.get("nextPTRSeason"):
                        print(f"  nextPTRSeason: {data['nextPTRSeason']}")

            except Exception as exc:
                print(f"  ERROR: {exc}")

        # Also try a broader introspection-style query
        print("\n" + "=" * 80)
        print("PROBING: Try with empty peakTimeEvents to see if there's another field")
        print("=" * 80)

        # Try querying more fields that might exist on PeakTimeRebateEnrollmentDetails
        introspection_query = """
        query getPeakTimeRebateEnrollmentDetails($params: PeakTimeRebateEnrollmentDetailsParams!) {
          getPeakTimeRebateEnrollmentDetails(params: $params) {
            enrollmentStatus
            cardType
            totalEarnedCredit
            activePTRSeason
            peakTimeEvents { eventDate eventEarnedCredit }
            seasonalDates { summer { start end } winter { start end } }
            lastPTRSeason
            nextPTRSeason
          }
        }
        """
        params = {
            "encryptedAccountNumber": enc_account,
            "ptrMockServerDate": "",
        }
        payload = {
            "query": introspection_query,
            "variables": {"params": params},
            "operationName": "getPeakTimeRebateEnrollmentDetails",
        }
        async with session.post(
            GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=TIMEOUT,
        ) as resp:
            body = await resp.json()
            print(json.dumps(body, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
