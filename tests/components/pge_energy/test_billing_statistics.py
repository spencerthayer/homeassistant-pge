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
    ProgramsSnapshot,
)
from custom_components.pge_energy.billing_statistics import (
    _floor_hour,
    _import_mean_point,
    async_cleanup_orphaned_billing_entity_mirrors,
    async_import_billing_snapshot,
    async_import_ledger_events,
    async_import_programs_metrics,
)
from custom_components.pge_energy.const import (
    ENTITY_UNIQUE_BILL_AVG_TEMPERATURE,
    ENTITY_UNIQUE_LIFETIME_BILLED,
    ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    STATISTIC_ID_SUFFIX_BILL_KWH,
    STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
)
from custom_components.pge_energy.store import ImportStoreData


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
    async def test_monetary_mean_imports_drop_entity_suffix(self):
        hass = MagicMock()
        snapshot = AccountSnapshot(
            account_number="123",
            amount_due=10.0,
            last_payment_amount=5.0,
            bill=BillDetails(avg_temperature_f=70.0),
        )
        with patch("custom_components.pge_energy.billing_statistics._import_mean_point") as mean:
            await async_import_billing_snapshot(hass, "key", "123", snapshot, datetime(2026, 7, 13, tzinfo=UTC))
            by_suffix = {c.kwargs["suffix"]: c.kwargs["entity_suffix"] for c in mean.call_args_list}
            assert by_suffix[STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE] is None
            assert by_suffix[STATISTIC_ID_SUFFIX_AMOUNT_DUE] is None
            assert by_suffix[STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT] is None
            assert by_suffix[STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE] == ENTITY_UNIQUE_BILL_AVG_TEMPERATURE

        with patch("custom_components.pge_energy.billing_statistics._import_mean_point") as mean:
            await async_import_programs_metrics(
                hass,
                "key",
                "123",
                ProgramsSnapshot(ytd_flex_load_earnings=12.0),
                datetime(2026, 7, 13, tzinfo=UTC),
            )
            assert mean.call_args.kwargs["suffix"] == STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS
            assert mean.call_args.kwargs["entity_suffix"] is None

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

    @pytest.mark.asyncio
    async def test_ledger_keeps_lifetime_entity_suffixes(self):
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
        with patch(
            "custom_components.pge_energy.billing_statistics._async_import_sum_series",
            new=AsyncMock(),
        ) as sum_series:
            await async_import_ledger_events(hass, "key", "123", events)
            by_suffix = {c.kwargs["suffix"]: c.kwargs["entity_suffix"] for c in sum_series.await_args_list}
            assert by_suffix[STATISTIC_ID_SUFFIX_BILL_AMOUNT] == ENTITY_UNIQUE_LIFETIME_BILLED
            assert by_suffix[STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT] == ENTITY_UNIQUE_LIFETIME_PAYMENTS
            assert by_suffix[STATISTIC_ID_SUFFIX_BILL_KWH] is None


@pytest.mark.asyncio
async def test_billing_mirror_cleanup_runs_once():
    hass = MagicMock()
    store = ImportStoreData(account_key="key", billing_mirror_cleanup_done=False)
    clear = MagicMock(side_effect=lambda ids, *, on_done=None: on_done() if on_done else None)
    instance = MagicMock()
    instance.async_clear_statistics = clear

    with (
        patch(
            "custom_components.pge_energy.billing_statistics.async_resolve_sensor_entity_id",
            side_effect=lambda hass, key, suffix: f"sensor.pge_{suffix}",
        ),
        patch(
            "custom_components.pge_energy.billing_statistics.get_instance",
            return_value=instance,
        ),
        patch(
            "custom_components.pge_energy.billing_statistics.async_save_import_state",
            new=AsyncMock(),
        ) as save,
    ):
        ok = await async_cleanup_orphaned_billing_entity_mirrors(
            hass, entry_id="entry1", account_key="key", store=store
        )
        assert ok is True
        assert store.billing_mirror_cleanup_done is True
        clear.assert_called_once()
        assert len(clear.call_args.args[0]) == 4
        save.assert_awaited_once()

        # Second call is a no-op once the flag is set.
        ok2 = await async_cleanup_orphaned_billing_entity_mirrors(
            hass, entry_id="entry1", account_key="key", store=store
        )
        assert ok2 is True
        assert clear.call_count == 1
        assert save.await_count == 1
