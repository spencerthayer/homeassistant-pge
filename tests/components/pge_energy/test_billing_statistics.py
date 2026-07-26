"""Unit tests for billing statistics helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.billing_models import (
    AccountSnapshot,
    BillDetails,
    LedgerEvent,
    LedgerEventType,
)
from custom_components.pge_energy.billing_statistics import (
    _floor_hour,
    _import_mean_point,
    async_import_billing_snapshot,
    async_import_ledger_events,
)
from custom_components.pge_energy.const import (
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
)


class TestFloorHour:
    def test_floors_to_utc_hour(self):
        when = datetime(2026, 7, 13, 7, 45, 30, tzinfo=UTC)
        assert _floor_hour(when) == datetime(2026, 7, 13, 7, 0, 0, tzinfo=UTC)


class TestImportMeanPoint:
    def test_skips_none_value(self):
        hass = MagicMock()
        with patch("custom_components.pge_energy.billing_statistics.async_add_external_statistics") as add:
            _import_mean_point(
                hass,
                "key",
                "123",
                suffix=STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
                entity_suffix=None,
                value=None,
                when=datetime(2026, 7, 13, tzinfo=UTC),
                unit="USD",
                unit_class=None,
                label="Balance",
            )
            add.assert_not_called()

    def test_writes_external_mean(self):
        hass = MagicMock()
        with (
            patch("custom_components.pge_energy.billing_statistics.async_add_external_statistics") as add,
            patch("custom_components.pge_energy.billing_statistics._async_mirror_entity_statistics"),
        ):
            _import_mean_point(
                hass,
                "key",
                "123",
                suffix=STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
                entity_suffix=None,
                value=300.13,
                when=datetime(2026, 7, 13, 7, 30, tzinfo=UTC),
                unit="USD",
                unit_class=None,
                label="Balance",
            )
            add.assert_called_once()
            _hass, meta, rows = add.call_args.args
            assert STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE in meta["statistic_id"]
            assert rows[0]["mean"] == 300.13


class TestAsyncImport:
    @pytest.mark.asyncio
    async def test_import_billing_snapshot_calls_mean_points(self):
        hass = MagicMock()
        snapshot = AccountSnapshot(
            account_number="123",
            amount_due=10.0,
            last_payment_amount=5.0,
            bill=BillDetails(avg_temperature_f=70.0),
        )
        with patch("custom_components.pge_energy.billing_statistics._import_mean_point") as mean:
            await async_import_billing_snapshot(hass, "key", "123", snapshot, datetime(2026, 7, 13, tzinfo=UTC))
            assert mean.call_count >= 3

    @pytest.mark.asyncio
    async def test_import_ledger_events_splits_bill_and_payment(self):
        hass = MagicMock()
        events = [
            LedgerEvent(
                event_type=LedgerEventType.BILL,
                date=datetime(2026, 7, 13, 7, tzinfo=UTC),
                amount_due=300.13,
                kwh=1358.0,
            ),
            LedgerEvent(
                event_type=LedgerEventType.PAYMENT,
                date=datetime(2026, 6, 30, 7, tzinfo=UTC),
                amount_paid=293.01,
            ),
        ]
        with (
            patch(
                "custom_components.pge_energy.billing_statistics._async_load_sum_states",
                new=AsyncMock(return_value={}),
            ),
            patch("custom_components.pge_energy.billing_statistics.async_add_external_statistics") as add,
            patch("custom_components.pge_energy.billing_statistics._async_mirror_entity_statistics"),
        ):
            await async_import_ledger_events(hass, "key", "123", events)
            written = [c.args[1]["statistic_id"] for c in add.call_args_list]
            assert any(STATISTIC_ID_SUFFIX_BILL_AMOUNT in s for s in written)
            assert any(STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT in s for s in written)
