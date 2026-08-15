from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.config_flow import (
    STEP_USER_DATA_SCHEMA,
    PGEConfigFlow,
    PGEOptionsFlow,
    _account_unique_id,
    _normalize_account_id,
    _options_schema,
    _resolve_discovered_account_id,
    _validate_usage_for_account,
)
from custom_components.pge_energy.const import (
    AUTH_MODE_CREDENTIAL,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_AUTH_MODE,
    CONF_AUTO_BACKFILL,
    CONF_BACKFILL_CONCURRENCY,
    CONF_BEARER_TOKEN,
    CONF_BILL_PDF_FORM,
    CONF_BILL_PDF_RETENTION,
    CONF_BILL_PDF_ROLLING_COUNT,
    CONF_CAPTURE_GRAPHQL_DIAGNOSTICS,
    CONF_CORRECTION_WINDOW,
    CONF_DOWNLOAD_BILL_PDFS,
    CONF_EMAIL,
    CONF_HISTORY_MODE,
    CONF_HISTORY_START_DATE,
    CONF_HOURLY_BACKFILL_DAYS,
    CONF_INCLUDE_BILLING,
    CONF_INCLUDE_COST,
    CONF_INCLUDE_DIAGNOSTICS,
    CONF_MANUAL_SYNC_ACTION,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_UNIT,
    CONF_SYNC_LOCAL_TIME,
    CONF_TOD_RATE_BASIC_SERVICE,
    CONF_TOD_RATE_MID_PEAK,
    CONF_TOD_RATE_OFF_PEAK,
    CONF_TOD_RATE_ON_PEAK,
    DEFAULT_SYNC_LOCAL_TIME,
    MANUAL_SYNC_ACTION_REFRESH,
    HistoryMode,
    PollingIntervalUnit,
)
from custom_components.pge_energy.exceptions import PGEAuthenticationError
from custom_components.pge_energy.portal_auth import PortalAuthResult


class TestPGEConfigFlow:
    def test_flow_init(self):
        flow = PGEConfigFlow()
        assert flow._token is None
        assert flow._encrypted_person_id is None
        assert flow._account_id is None

    @pytest.mark.asyncio
    async def test_validate_usage_success(self):
        mock_hass = MagicMock()
        mock_session = AsyncMock()

        with (
            patch(
                "custom_components.pge_energy.config_flow.aiohttp_client.async_get_clientsession",
                return_value=mock_session,
            ),
            patch("custom_components.pge_energy.config_flow.PGEApiClient") as mock_client,
        ):
            mock_client.return_value.get_usage = AsyncMock()
            await _validate_usage_for_account(
                mock_hass,
                token="token",
                encrypted_person_id="enc",
                account_id="acct",
                account_key="key1234567890ab",
            )

    @pytest.mark.asyncio
    async def test_validate_usage_auth_error(self):
        mock_hass = MagicMock()
        with (
            patch(
                "custom_components.pge_energy.config_flow.aiohttp_client.async_get_clientsession",
                return_value=AsyncMock(),
            ),
            patch("custom_components.pge_energy.config_flow.PGEApiClient") as mock_client,
        ):
            mock_client.return_value.get_usage = AsyncMock(side_effect=PGEAuthenticationError("Invalid token"))
            with pytest.raises(PGEAuthenticationError):
                await _validate_usage_for_account(
                    mock_hass,
                    token="bad_token",
                    encrypted_person_id="enc",
                    account_id="acct",
                    account_key="key1234567890ab",
                )

    def test_credential_schema(self):
        assert CONF_EMAIL in STEP_USER_DATA_SCHEMA.schema
        assert CONF_PASSWORD in STEP_USER_DATA_SCHEMA.schema
        assert CONF_ACCOUNT_ID in STEP_USER_DATA_SCHEMA.schema

    def test_normalize_and_resolve_account_id(self):
        assert _normalize_account_id("  1122334455  ") == "1122334455"
        assert _resolve_discovered_account_id("1122334455", ["1122334455", "999"]) == "1122334455"
        assert _resolve_discovered_account_id("112-233-4455", ["1122334455"]) == "1122334455"
        assert _resolve_discovered_account_id("111", ["222"]) is None
        assert _resolve_discovered_account_id("111", []) == "111"

    def test_account_unique_id_is_account_scoped(self):
        assert _account_unique_id("1122334455") == "pge_account_1122334455"
        # Same account under different emails must collide (one entry per account).
        assert _account_unique_id("A") == _account_unique_id(" A ")

    @pytest.mark.asyncio
    async def test_user_step_delegates_to_credential(self):
        flow = PGEConfigFlow()
        flow.hass = MagicMock()
        with patch.object(
            flow,
            "async_step_credential",
            AsyncMock(return_value={"type": "form", "step_id": "credential"}),
        ) as credential_step:
            result = await flow.async_step_user()
        credential_step.assert_awaited_once_with(None)
        assert result["step_id"] == "credential"

    @pytest.mark.asyncio
    async def test_credential_setup_uses_provided_account_number(self):
        flow = PGEConfigFlow()
        flow.hass = MagicMock()
        login = PortalAuthResult(
            access_token="tok",
            encrypted_person_id="enc",
            account_ids=["1122334455", "9999999999"],
            expires_at=None,
            refresh_credential="refresh",
        )
        with (
            patch(
                "custom_components.pge_energy.config_flow.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=login),
            ),
            patch.object(
                flow,
                "_async_finish_credential_entry",
                AsyncMock(return_value={"type": "create_entry"}),
            ) as finish,
        ):
            result = await flow.async_step_credential(
                {
                    CONF_EMAIL: "user@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_ACCOUNT_ID: "1122334455",
                }
            )
        assert result["type"] == "create_entry"
        assert flow._account_id == "1122334455"
        finish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_credential_setup_rejects_unknown_account_number(self):
        flow = PGEConfigFlow()
        flow.hass = MagicMock()
        login = PortalAuthResult(
            access_token="tok",
            encrypted_person_id="enc",
            account_ids=["1122334455"],
            expires_at=None,
            refresh_credential=None,
        )
        with patch(
            "custom_components.pge_energy.config_flow.portal_auth.async_login_or_refresh",
            AsyncMock(return_value=login),
        ):
            result = await flow.async_step_credential(
                {
                    CONF_EMAIL: "user@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_ACCOUNT_ID: "0000000000",
                }
            )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "account_not_found"

    def test_create_credential_entry(self):
        flow = PGEConfigFlow()
        flow._token = "test_token"
        flow._encrypted_person_id = "test_enc"
        flow._account_id = "test_acct"
        flow._account_key = "ffffffff00000000"
        flow._email = "user@example.com"
        flow._password = "secret"
        flow._auth_mode = AUTH_MODE_CREDENTIAL

        result = flow._create_entry()
        assert result["data"][CONF_AUTH_MODE] == AUTH_MODE_CREDENTIAL
        assert result["data"][CONF_EMAIL] == "user@example.com"
        assert result["data"][CONF_PASSWORD] == "secret"
        assert result["data"][CONF_BEARER_TOKEN] == "test_token"
        assert result["data"][CONF_ACCOUNT_ID] == "test_acct"

    def test_create_credential_entry_keeps_password_with_refresh(self):
        from custom_components.pge_energy.const import CONF_REFRESH_CREDENTIAL

        flow = PGEConfigFlow()
        flow._token = "test_token"
        flow._encrypted_person_id = "test_enc"
        flow._account_id = "test_acct"
        flow._account_key = "ffffffff00000000"
        flow._email = "user@example.com"
        flow._password = "secret"
        flow._refresh_credential = "durable-refresh"
        flow._auth_mode = AUTH_MODE_CREDENTIAL

        result = flow._create_entry()
        assert result["data"][CONF_REFRESH_CREDENTIAL] == "durable-refresh"
        assert result["data"][CONF_PASSWORD] == "secret"


class TestPGEOptionsFlow:
    def test_async_get_options_flow_returns_handler(self):
        entry = MagicMock()
        flow = PGEConfigFlow.async_get_options_flow(entry)
        assert isinstance(flow, PGEOptionsFlow)

    def test_options_schema_includes_settings_keys(self):
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        schema = _options_schema(entry)
        flat_keys = {getattr(field, "schema", field) for field in schema.schema}
        assert CONF_POLLING_INTERVAL in flat_keys
        assert CONF_POLLING_INTERVAL_UNIT in flat_keys
        assert CONF_SYNC_LOCAL_TIME in flat_keys
        assert CONF_CORRECTION_WINDOW in flat_keys
        assert CONF_HISTORY_MODE in flat_keys
        assert CONF_HISTORY_START_DATE in flat_keys
        assert CONF_HOURLY_BACKFILL_DAYS in flat_keys
        assert CONF_AUTO_BACKFILL in flat_keys
        assert CONF_INCLUDE_COST in flat_keys
        assert CONF_INCLUDE_DIAGNOSTICS in flat_keys
        assert CONF_CAPTURE_GRAPHQL_DIAGNOSTICS in flat_keys
        assert CONF_INCLUDE_BILLING in flat_keys
        assert CONF_BACKFILL_CONCURRENCY in flat_keys
        capture_field = next(
            field for field in schema.schema if getattr(field, "schema", field) == CONF_CAPTURE_GRAPHQL_DIAGNOSTICS
        )
        assert capture_field.default() is False

    def test_options_schema_accepts_blank_tod_rate_overrides(self):
        """Blank optional TOD NumberSelectors must not raise 'expected float'.

        HA OptionsFlow submits empty number boxes as None (or sometimes ""), and
        vol.Optional(..., default=None) also inserts None when the key is omitted.
        Sync settings Submit must succeed so diagnostic capture and other options
        can be saved (#5 comment).
        """
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        schema = _options_schema(entry)
        base = {
            CONF_POLLING_INTERVAL: 4,
            CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
            CONF_SYNC_LOCAL_TIME: DEFAULT_SYNC_LOCAL_TIME,
            CONF_CORRECTION_WINDOW: 7,
            CONF_HISTORY_MODE: HistoryMode.FULL.value,
            CONF_HISTORY_START_DATE: "2019-01-01",
            CONF_HOURLY_BACKFILL_DAYS: 90,
            CONF_AUTO_BACKFILL: True,
            CONF_INCLUDE_COST: True,
            CONF_INCLUDE_DIAGNOSTICS: True,
            CONF_CAPTURE_GRAPHQL_DIAGNOSTICS: True,
            CONF_INCLUDE_BILLING: True,
            CONF_DOWNLOAD_BILL_PDFS: False,
            CONF_BILL_PDF_FORM: "detailed",
            CONF_BILL_PDF_RETENTION: "latest",
            CONF_BILL_PDF_ROLLING_COUNT: 12,
            CONF_BACKFILL_CONCURRENCY: 2,
        }

        # Omitted keys (Optional defaults fill None, then must validate).
        assert schema(dict(base))

        for blank in (None, ""):
            payload = dict(base)
            payload.update(
                {
                    CONF_TOD_RATE_OFF_PEAK: blank,
                    CONF_TOD_RATE_MID_PEAK: blank,
                    CONF_TOD_RATE_ON_PEAK: blank,
                    CONF_TOD_RATE_BASIC_SERVICE: blank,
                }
            )
            validated = schema(payload)
            assert validated[CONF_CAPTURE_GRAPHQL_DIAGNOSTICS] is True
            assert validated[CONF_TOD_RATE_OFF_PEAK] in (None, "")
            assert validated[CONF_TOD_RATE_MID_PEAK] in (None, "")
            assert validated[CONF_TOD_RATE_ON_PEAK] in (None, "")
            assert validated[CONF_TOD_RATE_BASIC_SERVICE] in (None, "")

        with_rates = dict(base)
        with_rates.update(
            {
                CONF_TOD_RATE_OFF_PEAK: 0.0893,
                CONF_TOD_RATE_MID_PEAK: 0.167,
                CONF_TOD_RATE_ON_PEAK: 0.4313,
                CONF_TOD_RATE_BASIC_SERVICE: 0.12,
            }
        )
        validated_rates = schema(with_rates)
        assert validated_rates[CONF_TOD_RATE_OFF_PEAK] == pytest.approx(0.0893)
        assert validated_rates[CONF_TOD_RATE_ON_PEAK] == pytest.approx(0.4313)

    @pytest.mark.asyncio
    async def test_options_settings_saves_with_blank_tod_rates(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        result = await flow.async_step_settings(
            {
                CONF_POLLING_INTERVAL: 4,
                CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
                CONF_SYNC_LOCAL_TIME: DEFAULT_SYNC_LOCAL_TIME,
                CONF_CORRECTION_WINDOW: 7,
                CONF_HISTORY_MODE: HistoryMode.FULL.value,
                CONF_HISTORY_START_DATE: "2019-01-01",
                CONF_HOURLY_BACKFILL_DAYS: 90,
                CONF_AUTO_BACKFILL: True,
                CONF_INCLUDE_COST: True,
                CONF_INCLUDE_DIAGNOSTICS: True,
                CONF_CAPTURE_GRAPHQL_DIAGNOSTICS: True,
                CONF_INCLUDE_BILLING: True,
                CONF_DOWNLOAD_BILL_PDFS: False,
                CONF_BILL_PDF_FORM: "detailed",
                CONF_BILL_PDF_RETENTION: "latest",
                CONF_BILL_PDF_ROLLING_COUNT: 12,
                CONF_BACKFILL_CONCURRENCY: 2,
                CONF_TOD_RATE_OFF_PEAK: None,
                CONF_TOD_RATE_MID_PEAK: "",
                CONF_TOD_RATE_ON_PEAK: None,
                CONF_TOD_RATE_BASIC_SERVICE: "",
            }
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_CAPTURE_GRAPHQL_DIAGNOSTICS] is True
        assert result["data"][CONF_TOD_RATE_OFF_PEAK] is None
        assert result["data"][CONF_TOD_RATE_MID_PEAK] is None
        assert result["data"][CONF_TOD_RATE_ON_PEAK] is None
        assert result["data"][CONF_TOD_RATE_BASIC_SERVICE] is None

    @pytest.mark.asyncio
    async def test_options_init_shows_menu(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {}
        # OptionsFlow resolves config_entry via hass; stub properties used by step.
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        result = await flow.async_step_init()
        assert result["type"] == "menu"
        assert result["menu_options"] == ["settings", "panel", "credentials", "manual_sync"]

    @pytest.mark.asyncio
    async def test_options_panel_form_uses_domain_store(self):
        from custom_components.pge_energy.panel_settings import (
            CONF_DEFAULT_SECTION,
            CONF_REQUIRE_ADMIN,
            CONF_SHOW_SIDEBAR,
            CONF_SIDEBAR_ICON,
            CONF_SIDEBAR_TITLE,
            PanelSettings,
        )

        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {CONF_POLLING_INTERVAL: 4}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
        stored = PanelSettings(
            show_sidebar=False,
            sidebar_title="Custom",
            sidebar_icon="mdi:flash",
            require_admin=False,
            default_section="billing",
        )

        with patch(
            "custom_components.pge_energy.config_flow.async_load_panel_settings",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            result = await flow.async_step_panel()

        assert result["type"] == "form"
        assert result["step_id"] == "panel"
        schema_keys = {getattr(field, "schema", field) for field in result["data_schema"].schema}
        assert CONF_SHOW_SIDEBAR in schema_keys
        assert CONF_SIDEBAR_TITLE in schema_keys
        assert CONF_SIDEBAR_ICON in schema_keys
        assert CONF_REQUIRE_ADMIN in schema_keys
        assert CONF_DEFAULT_SECTION in schema_keys

    @pytest.mark.asyncio
    async def test_options_panel_save_aborts_without_touching_entry_options(self):
        from custom_components.pge_energy.panel_settings import PanelSettings

        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        original_options = {
            CONF_POLLING_INTERVAL: 4,
            CONF_INCLUDE_BILLING: True,
        }
        entry.options = dict(original_options)
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
        previous = PanelSettings()
        candidate_input = {
            "show_sidebar": False,
            "sidebar_title": "PGE",
            "sidebar_icon": "mdi:transmission-tower",
            "require_admin": True,
            "default_section": "usage",
        }

        with (
            patch(
                "custom_components.pge_energy.config_flow.async_load_panel_settings",
                new_callable=AsyncMock,
                return_value=previous,
            ),
            patch(
                "custom_components.pge_energy.config_flow.async_save_panel_settings",
                new_callable=AsyncMock,
            ) as save,
            patch(
                "custom_components.pge_energy.config_flow.async_apply_panel",
                new_callable=AsyncMock,
            ) as apply,
        ):
            result = await flow.async_step_panel(candidate_input)

        assert result["type"] == "abort"
        assert result["reason"] == "panel_updated"
        save.assert_awaited_once()
        apply.assert_awaited_once()
        assert entry.options == original_options
        flow.hass.config_entries.async_update_entry.assert_not_called()
        flow.hass.config_entries.async_reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_options_panel_validation_error_keeps_form(self):
        from custom_components.pge_energy.panel_settings import PanelSettings

        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        with (
            patch(
                "custom_components.pge_energy.config_flow.async_load_panel_settings",
                new_callable=AsyncMock,
                return_value=PanelSettings(),
            ),
            patch(
                "custom_components.pge_energy.config_flow.async_save_panel_settings",
                new_callable=AsyncMock,
            ) as save,
            patch(
                "custom_components.pge_energy.config_flow.async_apply_panel",
                new_callable=AsyncMock,
            ) as apply,
        ):
            result = await flow.async_step_panel(
                {
                    "show_sidebar": True,
                    "sidebar_title": "",
                    "sidebar_icon": "bad",
                    "require_admin": True,
                    "default_section": "glance",
                }
            )

        assert result["type"] == "form"
        assert result["errors"]["sidebar_title"] == "invalid_sidebar_title"
        assert result["errors"]["sidebar_icon"] == "invalid_sidebar_icon"
        save.assert_not_awaited()
        apply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_options_panel_apply_failure_restores_previous(self):
        from custom_components.pge_energy.panel_settings import PanelSettings

        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {CONF_POLLING_INTERVAL: 4}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
        previous = PanelSettings(sidebar_title="Old")

        with (
            patch(
                "custom_components.pge_energy.config_flow.async_load_panel_settings",
                new_callable=AsyncMock,
                return_value=previous,
            ),
            patch(
                "custom_components.pge_energy.config_flow.async_save_panel_settings",
                new_callable=AsyncMock,
            ) as save,
            patch(
                "custom_components.pge_energy.config_flow.async_apply_panel",
                new_callable=AsyncMock,
                side_effect=RuntimeError("apply failed"),
            ),
        ):
            result = await flow.async_step_panel(
                {
                    "show_sidebar": True,
                    "sidebar_title": "New",
                    "sidebar_icon": "mdi:flash",
                    "require_admin": True,
                    "default_section": "glance",
                }
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "panel_update_failed"
        assert save.await_count == 2
        assert save.await_args_list[1].args[1] == previous
        assert entry.options == {CONF_POLLING_INTERVAL: 4}

    @pytest.mark.asyncio
    async def test_options_settings_creates_entry(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        result = await flow.async_step_settings(
            {
                CONF_POLLING_INTERVAL: 6,
                CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
                CONF_SYNC_LOCAL_TIME: "03:30:00",
                CONF_CORRECTION_WINDOW: 7,
                CONF_HISTORY_MODE: HistoryMode.FULL.value,
                CONF_HISTORY_START_DATE: "2019-01-01",
                CONF_HOURLY_BACKFILL_DAYS: 90,
                CONF_AUTO_BACKFILL: True,
                CONF_INCLUDE_COST: True,
                CONF_INCLUDE_DIAGNOSTICS: False,
                CONF_CAPTURE_GRAPHQL_DIAGNOSTICS: True,
                CONF_INCLUDE_BILLING: True,
                CONF_BACKFILL_CONCURRENCY: 2,
            }
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_POLLING_INTERVAL] == 6
        assert result["data"][CONF_POLLING_INTERVAL_UNIT] == PollingIntervalUnit.HOURS.value
        assert result["data"][CONF_SYNC_LOCAL_TIME] == "03:30:00"
        assert result["data"][CONF_HISTORY_MODE] == HistoryMode.FULL.value
        assert result["data"][CONF_HOURLY_BACKFILL_DAYS] == 90
        assert result["data"][CONF_INCLUDE_DIAGNOSTICS] is False
        assert result["data"][CONF_CAPTURE_GRAPHQL_DIAGNOSTICS] is True
        assert result["data"][CONF_INCLUDE_BILLING] is True

    @pytest.mark.asyncio
    async def test_options_settings_requires_start_date(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {}
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        result = await flow.async_step_settings(
            {
                CONF_POLLING_INTERVAL: 6,
                CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
                CONF_SYNC_LOCAL_TIME: DEFAULT_SYNC_LOCAL_TIME,
                CONF_CORRECTION_WINDOW: 7,
                CONF_HISTORY_MODE: HistoryMode.START_DATE.value,
                CONF_HISTORY_START_DATE: "",
                CONF_HOURLY_BACKFILL_DAYS: 90,
                CONF_AUTO_BACKFILL: True,
                CONF_INCLUDE_COST: True,
                CONF_INCLUDE_DIAGNOSTICS: True,
                CONF_BACKFILL_CONCURRENCY: 2,
            }
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "history_start_required"

    @pytest.mark.asyncio
    async def test_options_manual_sync_busy_aborts(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {CONF_ACCOUNT_ID: "1071234567"}
        coordinator = MagicMock()
        coordinator.sync_job_in_progress = True
        coordinator.account_key = "abc"
        coordinator.sync_progress.status = "backfilling"
        coordinator.sync_progress.message = "Hourly 1/10"
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
        flow.hass.data = {"pge_energy": {"entry1": coordinator}}

        with patch(
            "custom_components.pge_energy.async_device_progress_path",
            return_value="/config/devices/device/dev1",
        ):
            result = await flow.async_step_manual_sync()
        assert result["type"] == "abort"
        assert result["reason"] == "sync_busy"

    @pytest.mark.asyncio
    async def test_options_manual_sync_starts_refresh(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {CONF_ACCOUNT_ID: "1071234567"}
        coordinator = MagicMock()
        coordinator.sync_job_in_progress = False
        coordinator.account_key = "abc"
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
        flow.hass.data = {"pge_energy": {"entry1": coordinator}}

        with (
            patch(
                "custom_components.pge_energy.async_device_progress_path",
                return_value="/config/devices/device/dev1",
            ),
            patch(
                "custom_components.pge_energy.async_start_manual_refresh",
                new=AsyncMock(return_value=None),
            ) as start,
        ):
            result = await flow.async_step_manual_sync({CONF_MANUAL_SYNC_ACTION: MANUAL_SYNC_ACTION_REFRESH})
        assert result["type"] == "abort"
        assert result["reason"] == "sync_started"
        start.assert_awaited_once_with(flow.hass, "entry1")

    @pytest.mark.asyncio
    async def test_options_credentials_shows_account_number(self):
        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {
            CONF_ACCOUNT_ID: "1071234567",
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "saved-secret",
        }
        flow.hass = MagicMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        result = await flow.async_step_credentials()
        assert result["type"] == "form"
        assert result["step_id"] == "credentials"
        assert result["description_placeholders"]["account_id"] == "1071234567"
        assert "saved and pre-filled" in result["description_placeholders"]["password_status"]
        flat_keys = {getattr(field, "schema", field) for field in result["data_schema"].schema}
        assert CONF_ACCOUNT_ID in flat_keys
        assert CONF_EMAIL in flat_keys
        assert CONF_PASSWORD in flat_keys
        # Stored password is the form default so the UI can mask/reveal it.
        password_marker = next(
            field for field in result["data_schema"].schema if getattr(field, "schema", field) == CONF_PASSWORD
        )
        assert password_marker.default() == "saved-secret"

    @pytest.mark.asyncio
    async def test_options_credentials_persists_password_with_refresh(self):
        from custom_components.pge_energy.const import CONF_REFRESH_CREDENTIAL
        from custom_components.pge_energy.portal_auth import PortalAuthResult

        flow = PGEOptionsFlow()
        entry = MagicMock()
        entry.entry_id = "entry1"
        entry.options = {}
        entry.data = {
            CONF_ACCOUNT_ID: "1071234567",
            CONF_EMAIL: "user@example.com",
            CONF_ACCOUNT_KEY: "abcd1234abcd1234",
        }
        flow.hass = MagicMock()
        flow.hass.config_entries.async_update_entry = MagicMock()
        flow.hass.config_entries.async_reload = AsyncMock()
        flow.handler = "entry1"
        flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

        login = PortalAuthResult(
            access_token="new-token",
            encrypted_person_id="enc",
            account_ids=["1071234567"],
            expires_at=None,
            refresh_credential="durable-refresh",
        )
        with patch(
            "custom_components.pge_energy.config_flow.portal_auth.async_login_or_refresh",
            AsyncMock(return_value=login),
        ):
            result = await flow.async_step_credentials(
                {
                    CONF_ACCOUNT_ID: "1071234567",
                    CONF_EMAIL: "user@example.com",
                    CONF_PASSWORD: "secret",
                }
            )
        assert result["type"] == "abort"
        assert result["reason"] == "credentials_updated"
        update_kwargs = flow.hass.config_entries.async_update_entry.call_args.kwargs
        assert update_kwargs["data"][CONF_PASSWORD] == "secret"
        assert update_kwargs["data"][CONF_REFRESH_CREDENTIAL] == "durable-refresh"
