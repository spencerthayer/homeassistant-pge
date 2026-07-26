from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.api import (
    PGEApiClient,
    _build_query,
    _parse_hourly_timestamp,
    _parse_interval,
    _parse_iso_timestamp,
    _parse_usage_response,
    _safe_decimal,
)
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGESchemaError,
)
from custom_components.pge_energy.models import UsageResolution

MOCK_HOURLY_INTERVAL = {
    "efficientSimilarHomesKwh": None,
    "intervalTime": "01-JUL-2025 00:00:00",
    "kwh": "1.57",
    "intervalSize": 900,
    "usageStatus": "kWh-Delivered",
    "rank": None,
    "similarHomesKwh": None,
    "amount": 0.29,
    "startDate": None,
    "endDate": None,
    "temperature": "70",
}

MOCK_DAILY_INTERVAL = {
    "efficientSimilarHomesKwh": "35.25",
    "intervalTime": "2026-06-07-00.00.00",
    "kwh": "47.0",
    "intervalSize": None,
    "usageStatus": None,
    "rank": None,
    "similarHomesKwh": "54.05",
    "amount": 10,
    "startDate": "2026-06-07T07:00:00.000Z",
    "endDate": "2026-06-08T07:00:00.000Z",
    "temperature": "56.96",
}


class TestTimestampParsing:
    def test_parse_hourly_timestamp(self):
        ts = _parse_hourly_timestamp("01-JUL-2025 00:00:00")
        assert ts == datetime(2025, 7, 1, 7, 0, 0, tzinfo=UTC)

    def test_parse_hourly_timestamp_afternoon(self):
        ts = _parse_hourly_timestamp("01-JUL-2025 14:30:00")
        assert ts == datetime(2025, 7, 1, 21, 30, 0, tzinfo=UTC)

    def test_parse_hourly_timestamp_invalid(self):
        with pytest.raises(PGESchemaError):
            _parse_hourly_timestamp("invalid")

    def test_parse_iso_timestamp(self):
        ts = _parse_iso_timestamp("2026-06-07T07:00:00.000Z")
        assert ts.year == 2026
        assert ts.month == 6
        assert ts.day == 7

    def test_parse_iso_timestamp_none(self):
        assert _parse_iso_timestamp(None) is None

    def test_parse_iso_timestamp_empty(self):
        assert _parse_iso_timestamp("") is None

    def test_parse_iso_timestamp_with_offset(self):
        ts = _parse_iso_timestamp("2026-06-07T07:00:00.000+00:00")
        assert ts is not None


class TestSafeDecimal:
    def test_string(self):
        assert _safe_decimal("47.0") == Decimal("47.0")

    def test_int(self):
        assert _safe_decimal(10) == Decimal("10")

    def test_float(self):
        assert _safe_decimal(0.29) is not None

    def test_none(self):
        assert _safe_decimal(None) is None

    def test_invalid(self):
        assert _safe_decimal("not_a_number") is None


class TestIntervalParsing:
    def test_hourly_interval(self):
        iv = _parse_interval(MOCK_HOURLY_INTERVAL, UsageResolution.HOURLY, "key1")
        assert iv is not None
        assert iv.kwh == Decimal("1.57")
        assert iv.amount == Decimal("0.29")
        assert iv.temperature == Decimal("70")
        assert iv.interval_size == 900
        assert iv.usage_status == "kWh-Delivered"
        assert iv.account_key == "key1"
        assert iv.resolution == UsageResolution.HOURLY

    def test_hourly_interval_start_end(self):
        iv = _parse_interval(MOCK_HOURLY_INTERVAL, UsageResolution.HOURLY, "key1")
        assert iv.start == datetime(2025, 7, 1, 7, 0, 0, tzinfo=UTC)
        assert iv.end == datetime(2025, 7, 1, 8, 0, 0, tzinfo=UTC)

    def test_daily_interval(self):
        iv = _parse_interval(MOCK_DAILY_INTERVAL, UsageResolution.DAILY, "key1")
        assert iv is not None
        assert iv.kwh == Decimal("47.0")
        assert iv.amount == Decimal("10")
        assert iv.start is not None
        assert iv.end is not None

    def test_interval_missing_kwh(self):
        raw = {**MOCK_HOURLY_INTERVAL, "kwh": None}
        with pytest.raises(PGESchemaError):
            _parse_interval(raw, UsageResolution.HOURLY, "key1")

    def test_interval_none_temperature(self):
        raw = {**MOCK_HOURLY_INTERVAL, "temperature": None}
        iv = _parse_interval(raw, UsageResolution.HOURLY, "key1")
        assert iv is not None
        assert iv.temperature is None


class TestQueryBuilding:
    def test_hourly_query(self):
        query = _build_query("hourlyUsageList")
        assert "hourlyUsageList" in query
        assert "GetUsageCompare" in query

    def test_daily_query(self):
        query = _build_query("dailyUsageList")
        assert "dailyUsageList" in query


class TestResponseParsing:
    def test_valid_hourly_response(self):
        raw_response = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "acctType": "RES",
                    "totalKwhUsage": "1230",
                    "totalKwhCost": "273",
                    "hourlyUsageList": [MOCK_HOURLY_INTERVAL],
                }
            }
        }
        resp = _parse_usage_response(raw_response, UsageResolution.HOURLY, "key1")
        assert len(resp.intervals) == 1
        assert resp.total_kwh == Decimal("1230")
        assert resp.total_cost == Decimal("273")
        assert resp.is_tod is False
        assert resp.acct_type == "RES"

    def test_missing_get_usage_compare(self):
        with pytest.raises(PGESchemaError):
            _parse_usage_response({"data": {}}, UsageResolution.HOURLY, "key1")

    def test_missing_list_field(self):
        raw = {"data": {"getUsageCompare": {"isCustomerEnrolledInTOD": False}}}
        with pytest.raises(PGESchemaError):
            _parse_usage_response(raw, UsageResolution.HOURLY, "key1")

    def test_empty_list(self):
        raw = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "hourlyUsageList": [],
                }
            }
        }
        resp = _parse_usage_response(raw, UsageResolution.HOURLY, "key1")
        assert len(resp.intervals) == 0


class TestApiClient:
    @pytest.mark.asyncio
    async def test_get_usage_success(self):
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "data": {
                    "getUsageCompare": {
                        "isCustomerEnrolledInTOD": False,
                        "acctType": "RES",
                        "totalKwhUsage": "100",
                        "totalKwhCost": "22",
                        "hourlyUsageList": [MOCK_HOURLY_INTERVAL],
                    }
                }
            }
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        client = PGEApiClient(mock_session, "token123", "enc_person", "acct123")
        now = datetime.now(UTC)
        resp = await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key1")
        assert len(resp.intervals) == 1

    @pytest.mark.asyncio
    async def test_get_usage_401(self):
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        client = PGEApiClient(mock_session, "expired_token", "enc", "acct")
        now = datetime.now(UTC)
        with pytest.raises(PGEAuthenticationError):
            await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key1")

    @pytest.mark.asyncio
    async def test_get_usage_502_retry(self):
        mock_session = AsyncMock()
        mock_response_502 = AsyncMock()
        mock_response_502.status = 502
        mock_response_502.__aenter__ = AsyncMock(return_value=mock_response_502)
        mock_response_502.__aexit__ = AsyncMock(return_value=False)

        mock_response_ok = AsyncMock()
        mock_response_ok.status = 200
        mock_response_ok.json = AsyncMock(
            return_value={
                "data": {
                    "getUsageCompare": {
                        "isCustomerEnrolledInTOD": False,
                        "hourlyUsageList": [MOCK_HOURLY_INTERVAL],
                    }
                }
            }
        )
        mock_response_ok.__aenter__ = AsyncMock(return_value=mock_response_ok)
        mock_response_ok.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_502
            return mock_response_ok

        mock_session.post = MagicMock(side_effect=side_effect)

        client = PGEApiClient(mock_session, "token", "enc", "acct")
        now = datetime.now(UTC)
        with patch("custom_components.pge_energy.api.asyncio.sleep", new_callable=AsyncMock):
            resp = await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key1")
        assert len(resp.intervals) == 1

    @pytest.mark.asyncio
    async def test_get_monthly_usage_paged_walks_backwards(self):
        from custom_components.pge_energy.models import UsageInterval, UsageResponse

        def _period(start: datetime, end: datetime) -> UsageInterval:
            return UsageInterval(
                account_key="key1",
                resolution=UsageResolution.MONTHLY,
                start=start,
                end=end,
                kwh=Decimal("100"),
                amount=Decimal("20"),
                temperature=None,
                usage_status=None,
                interval_size=None,
                source_timestamp=None,
            )

        page1 = [
            _period(datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC)),
            _period(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC)),
        ]
        page2 = [
            _period(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC)),
            _period(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
        ]

        client = PGEApiClient(MagicMock(), "token", "enc", "acct")
        calls: list[tuple[datetime, datetime]] = []

        async def fake_get_usage(resolution, start, end, account_key):
            assert resolution == UsageResolution.MONTHLY
            calls.append((start, end))
            intervals = page1 if len(calls) == 1 else page2
            return UsageResponse(
                resolution=UsageResolution.MONTHLY,
                intervals=intervals,
                total_kwh=None,
                total_cost=None,
                is_tod=False,
                acct_type="RES",
            )

        client.get_usage = fake_get_usage  # type: ignore[method-assign]
        resp = await client.get_monthly_usage_paged(
            datetime(2026, 2, 1, tzinfo=UTC),
            datetime(2026, 6, 1, tzinfo=UTC),
            "key1",
        )
        assert len(calls) == 2
        assert len(resp.intervals) == 4
        assert resp.total_kwh is None
