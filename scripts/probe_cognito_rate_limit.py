#!/usr/bin/env python3
"""Capped live probe of PGE Cognito InitiateAuth rate limits.

Safety rails (see plan):
  - Use PGE_EMAIL and PGE_PASSWORD environment variables
  - Prefer valid-password bursts (avoid failed-password lockout budget)
  - Hard stop on throttle / lock / MFA / CAPTCHA / HTTP 429
  - Absolute cap of 25 InitiateAuth calls per run
  - Failed-password probe capped at 3 unless --allow-lockout-probe

Usage (from repo root inside dev container; stop live HA first):
  python3 scripts/probe_cognito_rate_limit.py password-burst
  python3 scripts/probe_cognito_rate_limit.py refresh-burst
  python3 scripts/probe_cognito_rate_limit.py recovery
  python3 scripts/probe_cognito_rate_limit.py failed-password
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from custom_components.pge_energy.portal_auth import (  # noqa: E402
    COGNITO_AUTH_FLOW,
    COGNITO_CLIENT_ID,
    COGNITO_REFRESH_FLOW,
    COGNITO_URL,
    _cognito_headers,
)

MAX_INITIATE_AUTH = 25
MAX_FAILED_PASSWORD = 3
STOP_MARKERS = (
    "toomanyrequests",
    "limitexceeded",
    "password attempts exceeded",
    "userlambda",
    "mfa",
    "captcha",
    "recaptcha",
)


def _require_creds() -> tuple[str, str]:
    email = os.environ.get("PGE_EMAIL", "").strip()
    password = os.environ.get("PGE_PASSWORD", "")
    if not email or not password:
        raise SystemExit("Missing PGE_EMAIL / PGE_PASSWORD environment variables.")
    return email, password


def _should_hard_stop(status: int, payload: dict[str, Any]) -> str | None:
    if status == 429:
        return "http_429"
    err_type = str(payload.get("__type") or payload.get("code") or "")
    message = str(payload.get("message") or payload.get("Message") or "")
    combined = f"{err_type} {message}".lower()
    for marker in STOP_MARKERS:
        if marker in combined:
            return marker
    challenge = payload.get("ChallengeName") or payload.get("challengeName")
    if isinstance(challenge, str) and challenge:
        return f"challenge:{challenge}"
    return None


async def _initiate_auth(
    session: aiohttp.ClientSession,
    *,
    auth_flow: str,
    auth_parameters: dict[str, str],
) -> tuple[int, dict[str, Any], dict[str, str], float]:
    started = time.perf_counter()
    headers = _cognito_headers("AWSCognitoIdentityProviderService.InitiateAuth")
    body = {
        "AuthFlow": auth_flow,
        "ClientId": COGNITO_CLIENT_ID,
        "AuthParameters": auth_parameters,
    }
    async with session.post(COGNITO_URL, headers=headers, json=body) as resp:
        try:
            payload = await resp.json(content_type=None)
        except Exception:  # noqa: BLE001
            text = await resp.text()
            payload = {"_non_json": text[:200]}
        if not isinstance(payload, dict):
            payload = {"_unexpected": str(type(payload))}
        keep = ("retry-after", "content-type", "x-amzn-errortype")
        hdrs = {k: v for k, v in resp.headers.items() if k.lower() in keep}
        latency_ms = (time.perf_counter() - started) * 1000.0
        return resp.status, payload, hdrs, latency_ms


def _print_row(row: dict[str, Any]) -> None:
    print(json.dumps(row, separators=(",", ":")))


async def _run_burst(
    *,
    mode: str,
    max_calls: int,
    delay_s: float,
    wrong_password: bool = False,
    concurrency: int = 1,
) -> dict[str, Any]:
    email, password = _require_creds()
    if wrong_password:
        password = password + "__probe_invalid__"
    refresh_token: str | None = None
    calls = 0
    timeline: list[dict[str, Any]] = []
    stop_reason: str | None = None
    throttle_payload: dict[str, Any] | None = None
    throttle_headers: dict[str, str] | None = None

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Parallel wave first when concurrency > 1 (needed to exceed ~10 RPS).
        if concurrency > 1 and mode in ("password-burst", "failed-password"):
            wave = min(max_calls, concurrency)
            flow = COGNITO_AUTH_FLOW
            params = {"USERNAME": email, "PASSWORD": password}

            async def _one(idx: int) -> dict[str, Any]:
                status, payload, hdrs, latency_ms = await _initiate_auth(
                    session,
                    auth_flow=flow,
                    auth_parameters=params,
                )
                err_type = str(payload.get("__type") or "")
                message = str(payload.get("message") or payload.get("Message") or "")[:120]
                return {
                    "attempt": idx,
                    "flow": flow,
                    "status": status,
                    "latency_ms": round(latency_ms, 1),
                    "__type": err_type or None,
                    "message": message or None,
                    "retry_after": hdrs.get("Retry-After") or hdrs.get("retry-after"),
                    "ok": "AuthenticationResult" in payload,
                    "_payload": payload,
                    "_hdrs": hdrs,
                }

            results = await asyncio.gather(*[_one(i + 1) for i in range(wave)])
            calls = wave
            for row in sorted(results, key=lambda r: int(r["attempt"])):
                payload = row.pop("_payload")
                hdrs = row.pop("_hdrs")
                timeline.append(row)
                _print_row(row)
                stop = _should_hard_stop(int(row["status"]), payload)
                if stop and stop_reason is None:
                    stop_reason = stop
                    throttle_payload = {
                        "__type": payload.get("__type"),
                        "message": payload.get("message") or payload.get("Message"),
                    }
                    throttle_headers = hdrs
                if stop_reason is not None:
                    return {
                        "mode": mode,
                        "calls": calls,
                        "stop_reason": stop_reason,
                        "throttle_payload": throttle_payload,
                        "throttle_headers": throttle_headers,
                        "timeline": timeline,
                        "concurrency": concurrency,
                    }

        while calls < max_calls:
            if mode == "refresh-burst" and refresh_token is None:
                flow = COGNITO_AUTH_FLOW
                params = {"USERNAME": email, "PASSWORD": password}
            elif mode == "refresh-burst":
                flow = COGNITO_REFRESH_FLOW
                params = {"REFRESH_TOKEN": refresh_token}
            else:
                flow = COGNITO_AUTH_FLOW
                params = {"USERNAME": email, "PASSWORD": password}

            calls += 1
            status, payload, hdrs, latency_ms = await _initiate_auth(
                session,
                auth_flow=flow,
                auth_parameters=params,
            )
            err_type = str(payload.get("__type") or "")
            message = str(payload.get("message") or payload.get("Message") or "")[:120]
            row = {
                "attempt": calls,
                "flow": flow,
                "status": status,
                "latency_ms": round(latency_ms, 1),
                "__type": err_type or None,
                "message": message or None,
                "retry_after": hdrs.get("Retry-After") or hdrs.get("retry-after"),
                "ok": "AuthenticationResult" in payload,
            }
            timeline.append(row)
            _print_row(row)

            if mode == "refresh-burst" and refresh_token is None:
                result = payload.get("AuthenticationResult")
                if isinstance(result, dict):
                    refresh = result.get("RefreshToken")
                    if isinstance(refresh, str) and refresh:
                        refresh_token = refresh

            stop = _should_hard_stop(status, payload)
            if stop:
                stop_reason = stop
                throttle_payload = {
                    "__type": payload.get("__type"),
                    "message": payload.get("message") or payload.get("Message"),
                }
                throttle_headers = hdrs
                break

            if delay_s > 0:
                await asyncio.sleep(delay_s)

    return {
        "mode": mode,
        "calls": calls,
        "stop_reason": stop_reason,
        "throttle_payload": throttle_payload,
        "throttle_headers": throttle_headers,
        "timeline": timeline,
        "concurrency": concurrency,
    }


async def _run_recovery(*, max_calls: int, concurrency: int = 20) -> dict[str, Any]:
    """Burst until throttle, then back off until success or call budget exhausted."""
    burst = await _run_burst(
        mode="password-burst",
        max_calls=min(15, max_calls),
        delay_s=0.0,
        concurrency=concurrency,
    )
    remaining = max_calls - int(burst["calls"])
    if burst["stop_reason"] is None:
        return {**burst, "recovery_seconds": None, "recovery_note": "no_throttle_within_burst"}

    waits = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900]
    recovered_after: float | None = None
    started = time.monotonic()
    email, password = _require_creds()
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for wait in waits:
            if remaining <= 0:
                break
            await asyncio.sleep(wait)
            remaining -= 1
            status, payload, hdrs, latency_ms = await _initiate_auth(
                session,
                auth_flow=COGNITO_AUTH_FLOW,
                auth_parameters={"USERNAME": email, "PASSWORD": password},
            )
            row = {
                "attempt": "recovery",
                "wait_s": wait,
                "elapsed_s": round(time.monotonic() - started, 1),
                "flow": COGNITO_AUTH_FLOW,
                "status": status,
                "latency_ms": round(latency_ms, 1),
                "__type": payload.get("__type"),
                "message": str(payload.get("message") or "")[:120] or None,
                "retry_after": hdrs.get("Retry-After") or hdrs.get("retry-after"),
                "ok": "AuthenticationResult" in payload,
            }
            burst["timeline"].append(row)
            _print_row(row)
            if "AuthenticationResult" in payload:
                recovered_after = time.monotonic() - started
                break
            stop = _should_hard_stop(status, payload)
            if stop and stop not in (
                "toomanyrequests",
                "limitexceeded",
                "password attempts exceeded",
            ):
                burst["stop_reason"] = stop
                break

    return {
        **burst,
        "recovery_seconds": recovered_after,
        "calls": max_calls - remaining,
    }


def _write_fixture(path: Path, capture: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fixture = {
        "name": path.stem,
        "source": "live_capture_cognito_rate_probe",
        "request": {
            "method": "POST",
            "url": COGNITO_URL,
            "headers": {
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            },
            "body": {
                "AuthFlow": COGNITO_AUTH_FLOW,
                "ClientId": COGNITO_CLIENT_ID,
                "AuthParameters": {
                    "USERNAME": "<EMAIL>",
                    "PASSWORD": "<PASSWORD>",
                },
            },
        },
        "response": {
            "status": 400,
            "headers": capture.get("throttle_headers") or {"Content-Type": "application/x-amz-json-1.1"},
            "cookies": [],
            "body": capture.get("throttle_payload")
            or {
                "__type": "TooManyRequestsException",
                "message": "Too many requests",
            },
        },
        "probe_summary": {
            "mode": capture.get("mode"),
            "calls": capture.get("calls"),
            "stop_reason": capture.get("stop_reason"),
            "recovery_seconds": capture.get("recovery_seconds"),
        },
    }
    path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE_FIXTURE {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe PGE Cognito InitiateAuth rate limits")
    parser.add_argument("--max-calls", type=int, default=MAX_INITIATE_AUTH)
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between burst calls")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallel InitiateAuth wave size (password-burst / failed-password)",
    )
    parser.add_argument(
        "--fixture-out",
        default=None,
        help="Write sanitized throttle fixture JSON to this path when throttle observed",
    )
    parser.add_argument("--allow-lockout-probe", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("password-burst", help="Rapid USER_PASSWORD_AUTH with valid password")
    sub.add_parser("refresh-burst", help="One password login then rapid REFRESH_TOKEN_AUTH")
    sub.add_parser("recovery", help="Burst until throttle, then wait for success")
    sub.add_parser("failed-password", help="Capped wrong-password attempts")
    args = parser.parse_args(argv)

    max_calls = min(int(args.max_calls), MAX_INITIATE_AUTH)
    concurrency = max(1, min(int(args.concurrency), MAX_INITIATE_AUTH))

    if args.command == "password-burst":
        result = asyncio.run(
            _run_burst(
                mode="password-burst",
                max_calls=max_calls,
                delay_s=args.delay,
                concurrency=concurrency,
            ),
        )
    elif args.command == "refresh-burst":
        result = asyncio.run(_run_burst(mode="refresh-burst", max_calls=max_calls, delay_s=args.delay))
    elif args.command == "recovery":
        result = asyncio.run(_run_recovery(max_calls=max_calls, concurrency=concurrency))
    elif args.command == "failed-password":
        fail_max = max_calls if args.allow_lockout_probe else min(MAX_FAILED_PASSWORD, max_calls)
        result = asyncio.run(
            _run_burst(
                mode="failed-password",
                max_calls=fail_max,
                delay_s=max(args.delay, 0.5),
                wrong_password=True,
                concurrency=1,
            ),
        )
    else:
        return 64

    print("---SUMMARY---")
    print(
        json.dumps(
            {
                "mode": result.get("mode"),
                "calls": result.get("calls"),
                "stop_reason": result.get("stop_reason"),
                "recovery_seconds": result.get("recovery_seconds"),
                "throttle_payload": result.get("throttle_payload"),
                "throttle_headers": result.get("throttle_headers"),
            },
            indent=2,
        ),
    )

    if args.fixture_out and result.get("throttle_payload"):
        _write_fixture(Path(args.fixture_out), result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
