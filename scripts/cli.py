#!/usr/bin/env python3
"""Local CLI harness for PGE auth/API debugging without a running Home Assistant.

Usage (from repo root inside dev container):
  python3 scripts/cli.py validate
  python3 scripts/cli.py fetch --resolution hourly \
      --start-date 2025-07-01 --end-date 2025-07-03
  python3 scripts/cli.py login
  python3 scripts/cli.py renew

Secrets read directly from environment variables (or --ask): PGE_EMAIL, PGE_PASSWORD,
optional PGE_ACCOUNT_ID (or PGE_ACCOUNT_HINT) / PGE_REFRESH_CREDENTIAL.
validate/fetch/login/renew use portal_auth email/password.
Never pass secrets on argv.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.pge_energy import portal_auth  # noqa: E402
from custom_components.pge_energy.api import PGEApiClient  # noqa: E402
from custom_components.pge_energy.auth import PGEAuthManager, generate_immutable_account_key  # noqa: E402
from custom_components.pge_energy.billing_api import PGEBillingApiClient  # noqa: E402
from custom_components.pge_energy.day_validation import clip_hourly_to_local_day  # noqa: E402
from custom_components.pge_energy.exceptions import (  # noqa: E402
    PGEAuthenticationError,
    PGECaptchaUnsupportedError,
    PGEConnectionError,
    PGEDiscoveryIncompleteError,
    PGEGraphQLError,
    PGEMfaUnsupportedError,
    PGERateLimitError,
    PGESchemaError,
)
from custom_components.pge_energy.models import UsageResolution  # noqa: E402
from custom_components.pge_energy.time_util import iter_local_days, local_day_bounds, today_local  # noqa: E402

_LOGGER = logging.getLogger("pge_energy.cli")

EXIT_OK = 0
EXIT_AUTH = 2
EXIT_CONNECTION = 3
EXIT_SCHEMA = 4
EXIT_DISCOVERY = 5
EXIT_UNSUPPORTED = 6
EXIT_USAGE = 64


def _mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:2]}…{value[-keep:]}"


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value else None


def _require_credential_creds(*, ask: bool) -> tuple[str, str | None]:
    email = _env("PGE_EMAIL")
    password = _env("PGE_PASSWORD")
    if ask:
        email = email or input("PGE_EMAIL: ").strip()
        password = password or getpass.getpass("PGE_PASSWORD: ")
    if not email:
        raise SystemExit("Missing PGE_EMAIL")
    if not password:
        raise SystemExit("Missing PGE_PASSWORD")
    return email, password


def _yesterday_hourly_window() -> tuple[datetime, datetime]:
    day = today_local() - timedelta(days=1)
    day_start, day_end = local_day_bounds(day)
    return day_start, day_end - timedelta(milliseconds=1)


def _redact_interval(raw: dict[str, Any], *, show_ids: bool) -> dict[str, Any]:
    out = dict(raw)
    if show_ids:
        return out
    for key in ("account_key", "accountId", "encryptedPersonId"):
        if key in out and isinstance(out[key], str):
            out[key] = _mask(out[key])
    return out


async def _resolve_auth_manager(*, ask: bool) -> PGEAuthManager:
    """Login via portal_auth email/password credentials."""
    email, password = _require_credential_creds(ask=ask)
    if not password:
        raise SystemExit("Missing PGE_PASSWORD")
    try:
        result = await portal_auth.async_login_or_refresh(
            email=email,
            password=password,
            refresh_credential=_env("PGE_REFRESH_CREDENTIAL"),
        )
    except PGEDiscoveryIncompleteError as exc:
        raise SystemExit(f"DISCOVERY_INCOMPLETE: {exc}") from exc
    except PGEMfaUnsupportedError as exc:
        raise SystemExit(f"MFA_UNSUPPORTED: {exc}") from exc
    except PGECaptchaUnsupportedError as exc:
        raise SystemExit(f"CAPTCHA_UNSUPPORTED: {exc}") from exc
    except PGEAuthenticationError as exc:
        raise SystemExit(f"AUTH_FAILED: {exc}") from exc
    except PGEConnectionError as exc:
        raise SystemExit(f"CONNECTION_FAILED: {exc}") from exc

    preferred = _env("PGE_ACCOUNT_ID") or _env("PGE_ACCOUNT_HINT")
    if preferred and preferred in result.account_ids:
        account_id = preferred
    elif result.account_ids:
        account_id = result.account_ids[0]
    else:
        raise SystemExit("AUTH_FAILED: login succeeded but no account ids returned")
    return PGEAuthManager(
        token=result.access_token,
        encrypted_person_id=result.encrypted_person_id or "",
        account_id=account_id,
        account_key=generate_immutable_account_key(),
        email=email,
        password=password,
        refresh_credential=result.refresh_credential,
        auth_mode="credential",
        token_expires_at=result.expires_at,
    )


async def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        auth = await _resolve_auth_manager(ask=args.ask)
    except SystemExit as exc:
        msg = str(exc) if exc.code is None or not isinstance(exc.code, int) else (exc.args[0] if exc.args else "")
        if isinstance(msg, str) and msg.startswith("DISCOVERY_INCOMPLETE"):
            print(msg)
            return EXIT_DISCOVERY
        if isinstance(msg, str) and msg.startswith(("MFA_UNSUPPORTED", "CAPTCHA_UNSUPPORTED")):
            print(msg)
            return EXIT_UNSUPPORTED
        if isinstance(msg, str) and msg.startswith("AUTH_FAILED"):
            print(msg)
            return EXIT_AUTH
        if isinstance(msg, str) and msg.startswith("CONNECTION_FAILED"):
            print(msg)
            return EXIT_CONNECTION
        print(exc)
        return EXIT_USAGE

    start, end = _yesterday_hourly_window()
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = PGEApiClient(session, auth_manager=auth)
        try:
            resp = await client.get_usage(UsageResolution.HOURLY, start, end, auth.account_key)
        except PGEAuthenticationError as exc:
            print(f"AUTH_FAILED: {exc}")
            return EXIT_AUTH
        except (PGEConnectionError, PGERateLimitError) as exc:
            print(f"CONNECTION_FAILED: {exc}")
            return EXIT_CONNECTION
        except (PGESchemaError, PGEGraphQLError) as exc:
            print(f"SCHEMA_FAILED: {exc}")
            return EXIT_SCHEMA
        day = today_local() - timedelta(days=1)
        clipped = clip_hourly_to_local_day(day, resp.intervals)
        acct = auth.account_id if args.show_ids else _mask(auth.account_id)
        print(
            f"OK auth account={acct} hourly_raw={len(resp.intervals)} "
            f"hourly_clipped={len(clipped)} total_kwh={resp.total_kwh}",
        )
        return EXIT_OK


async def _cmd_fetch(args: argparse.Namespace) -> int:
    try:
        auth = await _resolve_auth_manager(ask=args.ask)
    except SystemExit as exc:
        msg = str(exc) if exc.args else str(exc)
        if isinstance(msg, str) and msg.startswith("DISCOVERY_INCOMPLETE"):
            print(msg)
            return EXIT_DISCOVERY
        if isinstance(msg, str) and msg.startswith(("MFA_UNSUPPORTED", "CAPTCHA_UNSUPPORTED")):
            print(msg)
            return EXIT_UNSUPPORTED
        if isinstance(msg, str) and msg.startswith("AUTH_FAILED"):
            print(msg)
            return EXIT_AUTH
        if isinstance(msg, str) and msg.startswith("CONNECTION_FAILED"):
            print(msg)
            return EXIT_CONNECTION
        print(exc)
        return EXIT_USAGE

    resolution = UsageResolution(args.resolution.upper())
    start = datetime.fromisoformat(args.start_date.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.end_date.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    timeout = aiohttp.ClientTimeout(total=60)
    rows_out: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = PGEApiClient(session, auth_manager=auth)
        try:
            if resolution == UsageResolution.HOURLY:
                for day in iter_local_days(start, end):
                    day_start, day_end = local_day_bounds(day)
                    request_end = day_end - timedelta(milliseconds=1)
                    resp = await client.get_usage(resolution, day_start, request_end, auth.account_key)
                    clipped = clip_hourly_to_local_day(day, resp.intervals)
                    total = sum(float(iv.kwh) for iv in clipped if iv.kwh is not None)
                    print(f"{day.isoformat()} rows_raw={len(resp.intervals)} rows={len(clipped)} kwh={total:.3f}")
                    for iv in clipped:
                        rows_out.append(
                            {
                                "start": iv.start.isoformat(),
                                "end": iv.end.isoformat(),
                                "kwh": str(iv.kwh),
                                "amount": str(iv.amount) if iv.amount is not None else None,
                                "account_key": iv.account_key,
                            },
                        )
            elif resolution == UsageResolution.MONTHLY:
                resp = await client.get_monthly_usage_paged(start, end, auth.account_key)
                print(f"rows={len(resp.intervals)} total_kwh={resp.total_kwh}")
                for iv in resp.intervals:
                    rows_out.append(
                        {
                            "start": iv.start.isoformat(),
                            "end": iv.end.isoformat(),
                            "kwh": str(iv.kwh),
                            "amount": str(iv.amount) if iv.amount is not None else None,
                            "account_key": iv.account_key,
                        },
                    )
            else:
                # DAILY: prefer ≥31d windows live; still allow caller-chosen range.
                resp = await client.get_usage(resolution, start, end, auth.account_key)
                print(f"rows={len(resp.intervals)} total_kwh={resp.total_kwh}")
                for iv in resp.intervals:
                    rows_out.append(
                        {
                            "start": iv.start.isoformat(),
                            "end": iv.end.isoformat(),
                            "kwh": str(iv.kwh),
                            "amount": str(iv.amount) if iv.amount is not None else None,
                            "account_key": iv.account_key,
                        },
                    )
        except PGEAuthenticationError as exc:
            print(f"AUTH_FAILED: {exc}")
            return EXIT_AUTH
        except (PGEConnectionError, PGERateLimitError) as exc:
            print(f"CONNECTION_FAILED: {exc}")
            return EXIT_CONNECTION
        except (PGESchemaError, PGEGraphQLError) as exc:
            print(f"SCHEMA_FAILED: {exc}")
            return EXIT_SCHEMA

    if args.json or args.out:
        payload = [_redact_interval(r, show_ids=args.show_ids) for r in rows_out]
        text = json.dumps(payload, indent=2)
        if args.out:
            _write_owner_only(Path(args.out), text + "\n")
        else:
            print(text)
    return EXIT_OK


def _write_owner_only(path: Path, text: str) -> None:
    """Atomically write with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


async def _cmd_login(args: argparse.Namespace) -> int:
    email, password = _require_credential_creds(ask=args.ask)
    try:
        result = await portal_auth.async_login_or_refresh(
            email=email,
            password=password,
            refresh_credential=_env("PGE_REFRESH_CREDENTIAL"),
        )
    except PGEDiscoveryIncompleteError as exc:
        print(f"DISCOVERY_INCOMPLETE: {exc}")
        return EXIT_DISCOVERY
    except PGEMfaUnsupportedError as exc:
        print(f"MFA_UNSUPPORTED: {exc}")
        return EXIT_UNSUPPORTED
    except PGECaptchaUnsupportedError as exc:
        print(f"CAPTCHA_UNSUPPORTED: {exc}")
        return EXIT_UNSUPPORTED
    except PGEAuthenticationError as exc:
        print(f"AUTH_FAILED: {exc}")
        return EXIT_AUTH
    except PGEConnectionError as exc:
        print(f"CONNECTION_FAILED: {exc}")
        return EXIT_CONNECTION

    accounts = result.account_ids if args.show_ids else [_mask(a) for a in result.account_ids]
    print(f"OK login accounts={accounts} expires_at={result.expires_at} has_refresh={bool(result.refresh_credential)}")
    return EXIT_OK


async def _cmd_billing_snapshot(args: argparse.Namespace) -> int:
    """Fetch AccountDetail snapshot (redacted unless --show-ids)."""
    auth = await _resolve_auth_manager(ask=args.ask)
    async with aiohttp.ClientSession() as session:
        client = PGEBillingApiClient(session, auth)
        snap = await client.get_account_detail(auth.account_id)
    payload = {
        "account_number": snap.account_number if args.show_ids else _mask(snap.account_number),
        "amount_due": snap.amount_due,
        "due_date": snap.due_date.isoformat() if snap.due_date else None,
        "last_payment_amount": snap.last_payment_amount,
        "autopay_enrolled": snap.autopay_enrolled,
        "paperless_enrolled": snap.paperless_enrolled,
        "has_encrypted_account": bool(snap.encrypted_account_number),
        "has_encrypted_premise": bool(snap.encrypted_premise_id),
        "has_encrypted_sa": bool(snap.encrypted_sa_id),
        "bill_kwh": snap.bill.kwh if snap.bill else None,
        "bill_avg_temp_f": snap.bill.avg_temperature_f if snap.bill else None,
    }
    print(json.dumps(payload, indent=2 if args.json else None))
    return EXIT_OK


async def _cmd_billing_history(args: argparse.Namespace) -> int:
    """Fetch one page of nested AccountDetail.paymentHistory."""
    auth = await _resolve_auth_manager(ask=args.ask)
    async with aiohttp.ClientSession() as session:
        client = PGEBillingApiClient(session, auth)
        snap = await client.get_account_detail(auth.account_id)
        events, total = await client.get_payment_history_page(
            snap.encrypted_account_number or "",
            snap.encrypted_person_id or auth.encrypted_person_id,
            account_number=auth.account_id,
            limit=int(args.limit),
            offset=int(args.offset),
        )
    rows = [
        {
            "type": e.event_type.value,
            "date": e.date.isoformat(),
            "amount_due": e.amount_due,
            "amount_paid": e.amount_paid,
            "kwh": e.kwh,
        }
        for e in events
    ]
    print(json.dumps({"total": total, "offset": args.offset, "rows": rows}, indent=2 if args.json else None))
    return EXIT_OK


async def _cmd_programs(args: argparse.Namespace) -> int:
    """Fetch program enrollment snapshot."""
    auth = await _resolve_auth_manager(ask=args.ask)
    async with aiohttp.ClientSession() as session:
        client = PGEBillingApiClient(session, auth)
        snap = await client.get_account_detail(auth.account_id)
        if not (snap.encrypted_account_number and snap.encrypted_premise_id and snap.encrypted_sa_id):
            print("PROGRAMS_FAILED: missing encrypted account/premise/SA ids")
            return EXIT_AUTH
        programs = await client.get_programs(
            snap.encrypted_account_number,
            snap.encrypted_premise_id,
            snap.encrypted_sa_id,
        )
    payload = {
        "peak_time_rebates_enrolled": programs.peak_time_rebates_enrolled,
        "green_future_enrolled": programs.green_future_enrolled,
        "green_future_pct": programs.green_future_pct,
        "time_of_day_enrolled": programs.time_of_day_enrolled,
        "smart_thermostat_enrolled": programs.smart_thermostat_enrolled,
        "habitat_support_enrolled": programs.habitat_support_enrolled,
        "ytd_flex_load_earnings": programs.ytd_flex_load_earnings,
        "on_bill_flex_load_earnings": programs.on_bill_flex_load_earnings,
    }
    print(json.dumps(payload, indent=2 if args.json else None))
    return EXIT_OK


async def _cmd_renew(args: argparse.Namespace) -> int:
    email, password = _require_credential_creds(ask=args.ask)
    auth = PGEAuthManager(
        token="",
        encrypted_person_id="",
        account_id=_env("PGE_ACCOUNT_ID") or _env("PGE_ACCOUNT_HINT") or "0",
        email=email,
        password=password,
        refresh_credential=_env("PGE_REFRESH_CREDENTIAL"),
        auth_mode="credential",
        token_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    try:
        first = await auth.ensure_valid_token()
        second = await auth.ensure_valid_token()
    except PGEDiscoveryIncompleteError as exc:
        print(f"DISCOVERY_INCOMPLETE: {exc}")
        return EXIT_DISCOVERY
    except PGEAuthenticationError as exc:
        print(f"AUTH_FAILED: {exc}")
        return EXIT_AUTH
    print(f"OK renew token_len={len(first)} stable={first == second} expires_at={auth.token_expires_at}")
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PGE Energy local CLI harness")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ask", action="store_true", help="Prompt for missing secrets")
    parser.add_argument(
        "--show-ids",
        action="store_true",
        help="Do not redact account/person identifiers in output",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "validate",
        help="Smoke-test credential login with HOURLY yesterday",
    )

    fetch = sub.add_parser("fetch", help="Fetch usage ranges via credential login")
    fetch.add_argument("--resolution", choices=["hourly", "daily", "monthly"], required=True)
    fetch.add_argument("--start-date", required=True)
    fetch.add_argument("--end-date", required=True)
    fetch.add_argument("--json", action="store_true")
    fetch.add_argument("--out", default=None)

    sub.add_parser("login", help="Credential login (discovery-gated)")
    sub.add_parser("renew", help="ensure_valid_token twice (discovery-gated)")

    billing_snap = sub.add_parser(
        "billing-snapshot",
        help="Fetch account/bill snapshot via getAccountDetailList",
    )
    billing_snap.add_argument("--json", action="store_true")

    billing_hist = sub.add_parser(
        "billing-history",
        help="Fetch a page of AccountDetail.paymentHistory",
    )
    billing_hist.add_argument("--limit", type=int, default=15)
    billing_hist.add_argument("--offset", type=int, default=0)
    billing_hist.add_argument("--page", type=int, default=None, help="Alias: offset=page*limit")
    billing_hist.add_argument("--json", action="store_true")

    programs = sub.add_parser("programs", help="Fetch program enrollment snapshot")
    programs.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "validate":
            return asyncio.run(_cmd_validate(args))
        if args.command == "fetch":
            return asyncio.run(_cmd_fetch(args))
        if args.command == "login":
            return asyncio.run(_cmd_login(args))
        if args.command == "renew":
            return asyncio.run(_cmd_renew(args))
        if args.command == "billing-snapshot":
            return asyncio.run(_cmd_billing_snapshot(args))
        if args.command == "billing-history":
            if getattr(args, "page", None) is not None:
                args.offset = int(args.page) * int(args.limit)
            return asyncio.run(_cmd_billing_history(args))
        if args.command == "programs":
            return asyncio.run(_cmd_programs(args))
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        print(exc)
        return EXIT_USAGE
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
