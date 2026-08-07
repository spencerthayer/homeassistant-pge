from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.api import (
    ALPHA_CAPTURE_PREFIX,
    PGEApiClient,
    _build_query,
    _capture_rows,
    _introspection_summary,
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


def _mock_http_response(status: int, *, json_data=None, text: str = "") -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data)
    response.text = AsyncMock(return_value=text)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


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

    def test_interval_null_kwh_is_unavailable_sample(self):
        raw = {**MOCK_HOURLY_INTERVAL, "kwh": None, "amount": None}
        iv = _parse_interval(raw, UsageResolution.HOURLY, "key1")
        assert iv.kwh is None
        assert iv.amount is None
        assert iv.start is not None

    def test_interval_unparsable_kwh_still_errors(self):
        raw = {**MOCK_HOURLY_INTERVAL, "kwh": "not-a-number"}
        with pytest.raises(PGESchemaError, match="Interval kwh must be numeric"):
            _parse_interval(raw, UsageResolution.HOURLY, "key1")

    def test_signed_export_interval(self):
        raw = {**MOCK_HOURLY_INTERVAL, "kwh": "-2.26", "amount": -0.42}
        iv = _parse_interval(raw, UsageResolution.HOURLY, "key1")
        assert iv.kwh == Decimal("-2.26")
        assert iv.amount == Decimal("-0.42")

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


class TestAlphaCaptureHelpers:
    def test_capture_rows_allowlists_and_sanitizes(self):
        raw = {
            "data": {
                "getUsageCompare": {
                    "hourlyUsageList": [
                        {
                            **MOCK_HOURLY_INTERVAL,
                            "temperature": "user@example.com eyJabc.def.ghi 1234567890",
                            "unexpectedSecret": "must-not-appear",
                        }
                    ],
                    "accountId": "1234567890",
                }
            }
        }
        rows = _capture_rows(raw, "hourlyUsageList")
        assert len(rows) == 1
        assert set(rows[0]) == {
            "intervalTime",
            "startDate",
            "endDate",
            "kwh",
            "amount",
            "usageStatus",
            "intervalSize",
            "temperature",
        }
        assert rows[0]["temperature"] == "[email] [jwt] [id]"
        assert "unexpectedSecret" not in rows[0]

    def test_capture_rows_are_bounded(self):
        raw = {
            "data": {
                "getUsageCompare": {
                    "hourlyUsageList": [{**MOCK_HOURLY_INTERVAL, "temperature": "x" * 500} for _ in range(50)]
                }
            }
        }
        rows = _capture_rows(raw, "hourlyUsageList")
        assert len(rows) == 40
        assert rows[0]["temperature"] == "x" * 120

    def test_introspection_summary_keeps_usage_contract_and_direction_fields(self):
        raw = {
            "data": {
                "__schema": {
                    "queryType": {
                        "fields": [
                            {
                                "name": "getUsageCompare",
                                "args": [{"name": "params", "type": {"name": "GetUsageCompareParams"}}],
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {
                                        "kind": "LIST",
                                        "ofType": {
                                            "kind": "NON_NULL",
                                            "ofType": {"name": "UsageCompareResponse"},
                                        },
                                    },
                                },
                            },
                            {
                                "name": "getSolarExport",
                                "args": [{"name": "params", "type": {"name": "SolarExportParams"}}],
                                "type": {"name": "SolarExport"},
                            },
                            {"name": "unrelated", "args": [], "type": {"name": "Other"}},
                        ]
                    },
                    "types": [
                        {
                            "kind": "INPUT_OBJECT",
                            "name": "GetUsageCompareParams",
                            "inputFields": [{"name": "displayMode"}, {"name": "accountId"}],
                        },
                        {
                            "kind": "OBJECT",
                            "name": "UsageCompareResponse",
                            "fields": [{"name": "hourlyUsageList"}, {"name": "receivedKwh"}],
                        },
                        {
                            "kind": "OBJECT",
                            "name": "Other",
                            "fields": [{"name": "ignored"}, {"name": "oneTimePayment"}],
                        },
                        {
                            "kind": "INPUT_OBJECT",
                            "name": "SolarExportParams",
                            "inputFields": [{"name": "encryptedAccountNumber"}],
                        },
                    ],
                }
            }
        }
        summary = _introspection_summary(raw)
        assert [field["name"] for field in summary["query_fields"]] == ["getUsageCompare", "getSolarExport"]
        types = {item["name"]: item for item in summary["types"]}
        assert types["GetUsageCompareParams"]["input_fields"] == ["displayMode", "accountId"]
        assert types["UsageCompareResponse"]["fields"] == ["hourlyUsageList", "receivedKwh"]
        assert types["SolarExportParams"]["input_fields"] == ["encryptedAccountNumber"]
        assert "Other" not in types


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
        assert mock_session.post.call_count == 1
        assert client.introspection_attempted is False
        assert client.captured_response_count == 0

    @pytest.mark.asyncio
    async def test_opt_in_capture_logs_rows_and_introspects_once(self, caplog):
        usage_data = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "hourlyUsageList": [
                        {**MOCK_HOURLY_INTERVAL, "kwh": "-1.5", "amount": -0.2},
                        {**MOCK_HOURLY_INTERVAL, "kwh": "0.5", "amount": 0.1},
                    ],
                    "accountId": "1234567890",
                }
            },
            "token": "eyJabc.def.ghi",
        }
        introspection_data = {
            "data": {
                "__schema": {
                    "queryType": {
                        "fields": [
                            {
                                "name": "getUsageCompare",
                                "args": [{"name": "params", "type": {"name": "GetUsageCompareParams"}}],
                                "type": {"name": "UsageCompareResponse"},
                            }
                        ]
                    },
                    "types": [
                        {
                            "kind": "OBJECT",
                            "name": "UsageCompareResponse",
                            "fields": [{"name": "receivedKwh"}],
                        }
                    ],
                }
            }
        }
        session = MagicMock()
        session.post = MagicMock(
            side_effect=[
                _mock_http_response(200, json_data=usage_data),
                _mock_http_response(200, json_data=introspection_data),
                _mock_http_response(200, json_data=usage_data),
            ]
        )
        client = PGEApiClient(
            session,
            "secret-token",
            "secret-person",
            "1234567890",
            capture_graphql_diagnostics=True,
        )
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = start + timedelta(days=1)
        with caplog.at_level("INFO", logger="custom_components.pge_energy.api"):
            first = await client.get_usage(UsageResolution.HOURLY, start, end, "secret-key")
            second = await client.get_usage(UsageResolution.HOURLY, start, end, "secret-key")

        assert len(first.intervals) == len(second.intervals) == 2
        assert session.post.call_count == 3
        assert client.introspection_attempted is True
        assert client.captured_response_count == 1
        introspection_call = session.post.call_args_list[1]
        assert introspection_call.args[0] == "https://apix.portlandgeneral.com/pge-graphql"
        assert introspection_call.kwargs["allow_redirects"] is False
        text = caplog.text
        assert ALPHA_CAPTURE_PREFIX in text
        assert '"negative_kwh_count":1' in text
        assert '"negative_amount_count":1' in text
        assert '"max_rows_per_start":2' in text
        assert "receivedKwh" in text
        assert "secret-token" not in text
        assert "secret-person" not in text
        assert "secret-key" not in text
        assert "1234567890" not in text
        assert "eyJabc.def.ghi" not in text

    @pytest.mark.asyncio
    async def test_introspection_failure_does_not_fail_usage(self, caplog):
        usage_data = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "hourlyUsageList": [MOCK_HOURLY_INTERVAL],
                }
            }
        }
        session = MagicMock()
        session.post = MagicMock(
            side_effect=[
                _mock_http_response(200, json_data=usage_data),
                _mock_http_response(403, text="account 1234567890 rejected"),
            ]
        )
        client = PGEApiClient(session, "token", "person", "account", capture_graphql_diagnostics=True)
        now = datetime.now(UTC)
        with caplog.at_level("INFO", logger="custom_components.pge_energy.api"):
            response = await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key")
        assert len(response.intervals) == 1
        assert client.introspection_attempted is True
        assert "introspection=failed status=403" in caplog.text
        assert "1234567890" not in caplog.text

    @pytest.mark.asyncio
    async def test_capture_processing_exception_does_not_fail_usage(self, caplog):
        usage_data = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "hourlyUsageList": [MOCK_HOURLY_INTERVAL],
                }
            }
        }
        introspection_data = {"data": {"__schema": {"queryType": {"fields": []}, "types": []}}}
        session = MagicMock()
        session.post = MagicMock(
            side_effect=[
                _mock_http_response(200, json_data=usage_data),
                _mock_http_response(200, json_data=introspection_data),
            ]
        )
        client = PGEApiClient(session, "token", "person", "account", capture_graphql_diagnostics=True)
        now = datetime.now(UTC)
        with (
            caplog.at_level("INFO", logger="custom_components.pge_energy.api"),
            patch.object(client, "_log_usage_capture", side_effect=ValueError("bad private@example.com")),
        ):
            response = await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key")

        assert len(response.intervals) == 1
        assert session.post.call_count == 2
        assert "processing=failed error_type=ValueError" in caplog.text
        assert "private@example.com" not in caplog.text

    @pytest.mark.asyncio
    async def test_null_kwh_is_captured_and_parsed_as_unavailable(self, caplog):
        usage_data = {
            "data": {
                "getUsageCompare": {
                    "isCustomerEnrolledInTOD": False,
                    "hourlyUsageList": [{**MOCK_HOURLY_INTERVAL, "kwh": None, "usageStatus": "kWh-Received"}],
                }
            }
        }
        introspection_data = {"data": {"__schema": {"queryType": {"fields": []}, "types": []}}}
        session = MagicMock()
        session.post = MagicMock(
            side_effect=[
                _mock_http_response(200, json_data=usage_data),
                _mock_http_response(200, json_data=introspection_data),
            ]
        )
        client = PGEApiClient(session, "token", "person", "account", capture_graphql_diagnostics=True)
        now = datetime.now(UTC)
        with caplog.at_level("INFO", logger="custom_components.pge_energy.api"):
            resp = await client.get_usage(UsageResolution.HOURLY, now - timedelta(days=1), now, "key")

        assert session.post.call_count == 2
        assert client.introspection_attempted is True
        assert '"usageStatus":"kWh-Received"' in caplog.text
        assert len(resp.intervals) == 1
        assert resp.intervals[0].kwh is None

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
