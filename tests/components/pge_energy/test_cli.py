from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import cli, portal_auth
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGEDiscoveryIncompleteError,
    PGESchemaError,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution, UsageResponse
from custom_components.pge_energy.time_util import iter_local_days, local_day_bounds


def _usage(intervals: list[UsageInterval] | None = None) -> UsageResponse:
    return UsageResponse(
        resolution=UsageResolution.HOURLY,
        intervals=intervals or [],
        total_kwh=Decimal("1.5"),
        total_cost=None,
        is_tod=False,
        acct_type="RES",
    )


def _interval(day: date, hour: int = 0) -> UsageInterval:
    day_start, _ = local_day_bounds(day)
    start = day_start + timedelta(hours=hour)
    return UsageInterval(
        account_key="acctkey12345678",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal("1.0"),
        amount=Decimal("0.1"),
        temperature=None,
        usage_status="kWh-Delivered",
        interval_size=900,
        source_timestamp=None,
    )


class TestCliHelpers:
    def test_mask_redacts(self):
        assert cli._mask("abcdef1234") == "ab…1234"
        assert cli._mask("ab") == "**"

    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0


def _login_result(account_id: str = "acct0001") -> portal_auth.PortalAuthResult:
    return portal_auth.PortalAuthResult(
        access_token="tok",
        encrypted_person_id="person",
        account_ids=[account_id],
        expires_at=None,
        refresh_credential="refresh",
    )


def _set_credential_env(monkeypatch, *, account_id: str = "acct0001") -> None:
    monkeypatch.delenv("PGE_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("PGE_ENCRYPTED_PERSON_ID", raising=False)
    monkeypatch.setenv("PGE_EMAIL", "user@example.com")
    monkeypatch.setenv("PGE_PASSWORD", "secret")
    monkeypatch.setenv("PGE_ACCOUNT_ID", account_id)


class TestCliValidate:
    def test_missing_env(self, monkeypatch):
        monkeypatch.delenv("PGE_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("PGE_ENCRYPTED_PERSON_ID", raising=False)
        monkeypatch.delenv("PGE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("PGE_EMAIL", raising=False)
        monkeypatch.delenv("PGE_PASSWORD", raising=False)
        code = cli.main(["validate"])
        assert code == cli.EXIT_USAGE

    def test_credential_chain(self, monkeypatch, capsys):
        _set_credential_env(monkeypatch, account_id="0000000000")
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(return_value=_usage())

        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result("0000000000")),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(["validate"])
        assert code == cli.EXIT_OK
        assert "OK auth" in capsys.readouterr().out
        assert mock_client.get_usage.await_args.args[0] == UsageResolution.HOURLY

    def test_auth_failed(self, monkeypatch):
        _set_credential_env(monkeypatch)
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(side_effect=PGEAuthenticationError("bad"))

        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result()),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(["validate"])
        assert code == cli.EXIT_AUTH

    def test_ok(self, monkeypatch, capsys):
        _set_credential_env(monkeypatch)
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(return_value=_usage())

        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result()),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(["validate"])
        assert code == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "OK auth" in out
        assert "acct0001" not in out


class TestCliFetch:
    def test_hourly_iterates_local_days(self, monkeypatch):
        _set_credential_env(monkeypatch)

        days = list(
            iter_local_days(
                datetime(2025, 7, 1, tzinfo=UTC),
                datetime(2025, 7, 3, tzinfo=UTC),
            )
        )
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(side_effect=[_usage([_interval(d)]) for d in days])

        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result()),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(
                [
                    "fetch",
                    "--resolution",
                    "hourly",
                    "--start-date",
                    "2025-07-01",
                    "--end-date",
                    "2025-07-03",
                ]
            )
        assert code == cli.EXIT_OK
        assert mock_client.get_usage.await_count == len(days)

    def test_json_redacts_account_key(self, monkeypatch, capsys):
        _set_credential_env(monkeypatch)

        day = date(2025, 7, 1)
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(return_value=_usage([_interval(day)]))

        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result()),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
            patch(
                "custom_components.pge_energy.cli.iter_local_days",
                return_value=[day],
            ),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(
                [
                    "fetch",
                    "--resolution",
                    "hourly",
                    "--start-date",
                    "2025-07-01",
                    "--end-date",
                    "2025-07-01",
                    "--json",
                ]
            )
        assert code == cli.EXIT_OK
        out = capsys.readouterr().out
        json_start = out.index("[")
        payload = json.loads(out[json_start:])
        assert payload[0]["account_key"] != "acctkey12345678"
        assert "…" in payload[0]["account_key"] or "*" in payload[0]["account_key"]

    def test_schema_exit(self, monkeypatch):
        _set_credential_env(monkeypatch)
        mock_client = MagicMock()
        mock_client.get_usage = AsyncMock(side_effect=PGESchemaError("bad"))
        with (
            patch(
                "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=_login_result()),
            ),
            patch("custom_components.pge_energy.cli.aiohttp.ClientSession") as session_cls,
            patch("custom_components.pge_energy.cli.PGEApiClient", return_value=mock_client),
        ):
            session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            session_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            code = cli.main(
                [
                    "fetch",
                    "--resolution",
                    "daily",
                    "--start-date",
                    "2025-07-01",
                    "--end-date",
                    "2025-07-02",
                ]
            )
        assert code == cli.EXIT_SCHEMA


class TestCliLogin:
    def test_discovery_incomplete(self, monkeypatch):
        monkeypatch.setenv("PGE_EMAIL", "user@example.com")
        monkeypatch.setenv("PGE_PASSWORD", "secret")
        with patch(
            "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
            AsyncMock(side_effect=PGEDiscoveryIncompleteError("nope")),
        ):
            code = cli.main(["login"])
        assert code == cli.EXIT_DISCOVERY

    def test_login_ok(self, monkeypatch, capsys):
        monkeypatch.setenv("PGE_EMAIL", "user@example.com")
        monkeypatch.setenv("PGE_PASSWORD", "secret")
        result = portal_auth.PortalAuthResult(
            access_token="tok",
            encrypted_person_id="person",
            account_ids=["0000000000"],
            expires_at=None,
            refresh_credential="refresh",
        )
        with patch(
            "custom_components.pge_energy.cli.portal_auth.async_login_or_refresh",
            AsyncMock(return_value=result),
        ):
            code = cli.main(["login"])
        assert code == cli.EXIT_OK
        assert "OK login" in capsys.readouterr().out
