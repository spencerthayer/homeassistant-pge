from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from . import portal_auth
from .api import PGEApiClient
from .auth import PGEAuthManager, generate_immutable_account_key
from .billing_api import PGEBillingApiClient
from .const import (
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
    CONF_ENCRYPTED_ACCOUNT_NUMBER,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_ENCRYPTED_PREMISE_ID,
    CONF_ENCRYPTED_SA_ID,
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
    CONF_REFRESH_CREDENTIAL,
    CONF_SYNC_LOCAL_TIME,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_AUTO_BACKFILL,
    DEFAULT_BACKFILL_CONCURRENCY,
    DEFAULT_BILL_PDF_FORM,
    DEFAULT_BILL_PDF_RETENTION,
    DEFAULT_BILL_PDF_ROLLING_COUNT,
    DEFAULT_CAPTURE_GRAPHQL_DIAGNOSTICS,
    DEFAULT_CORRECTION_WINDOW,
    DEFAULT_DOWNLOAD_BILL_PDFS,
    DEFAULT_HISTORY_FLOOR_ISO,
    DEFAULT_HISTORY_MODE,
    DEFAULT_HOURLY_BACKFILL_DAYS,
    DEFAULT_INCLUDE_BILLING,
    DEFAULT_INCLUDE_COST,
    DEFAULT_INCLUDE_DIAGNOSTICS,
    DEFAULT_SYNC_LOCAL_TIME,
    DOMAIN,
    MANUAL_SYNC_ACTION_BACKFILL,
    MANUAL_SYNC_ACTION_REFRESH,
    MAX_BACKFILL_CONCURRENCY,
    MAX_CORRECTION_WINDOW,
    MIN_CORRECTION_WINDOW,
    HistoryMode,
    PollingIntervalUnit,
)
from .exceptions import (
    PGEAuthenticationError,
    PGECaptchaUnsupportedError,
    PGEConnectionError,
    PGEDiscoveryIncompleteError,
    PGEMfaUnsupportedError,
)
from .models import UsageResolution
from .options import (
    get_entry_option,
    parse_sync_local_time,
    pge_display_name,
    polling_interval_to_minutes,
    resolve_polling_interval_form_defaults,
    resolve_sync_local_time,
)
from .panel import async_apply_panel
from .panel_settings import (
    CONF_DEFAULT_SECTION,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_SIDEBAR,
    CONF_SIDEBAR_ICON,
    CONF_SIDEBAR_TITLE,
    PANEL_DEFAULT_SECTIONS,
    PANEL_SECTION_LABELS,
    PanelSettings,
    PanelSettingsValidationError,
    async_load_panel_settings,
    async_save_panel_settings,
    normalize_panel_settings,
)
from .time_util import local_day_bounds, today_local

_LOGGER = logging.getLogger(__name__)


def _yesterday_hourly_window() -> tuple[datetime, datetime]:
    """Closed-day HOURLY window used for live connection validation.

    DAILY ranges under ~31 days hard-error on the live API; yesterday HOURLY
    is the reliable smoke-test shape.
    """
    day = today_local() - timedelta(days=1)
    day_start, day_end = local_day_bounds(day)
    return day_start, day_end - timedelta(milliseconds=1)


_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
        vol.Required(CONF_ACCOUNT_ID): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)


def _normalize_account_id(value: str) -> str:
    return value.strip()


def _account_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _resolve_discovered_account_id(provided: str, discovered: list[str]) -> str | None:
    """Map a user-entered account number onto a discovered id.

    When discovery returned accounts, require a match (exact or digits-only).
    When discovery returned none, accept the provided value for usage validation.
    """
    normalized = _normalize_account_id(provided)
    if not normalized:
        return None
    if not discovered:
        return normalized
    if normalized in discovered:
        return normalized
    provided_digits = _account_digits(normalized)
    if not provided_digits:
        return None
    for candidate in discovered:
        if _account_digits(candidate) == provided_digits:
            return candidate
    return None


def _account_unique_id(account_id: str) -> str:
    """Stable unique id keyed by PGE account number (not email)."""
    return f"pge_account_{_normalize_account_id(account_id)}"


def _credential_unique_id(email: str, account_id: str) -> str:
    """Legacy unique-id helper retained for older tests/callers."""
    digest = hashlib.sha256(f"{email.lower().strip()}:{account_id}".encode()).hexdigest()[:32]
    return f"pge_cred_{digest}"


async def _validate_usage_for_account(
    hass: HomeAssistant,
    *,
    token: str,
    encrypted_person_id: str,
    account_id: str,
    account_key: str,
) -> None:
    session = aiohttp_client.async_get_clientsession(hass)
    auth = PGEAuthManager(
        token=token,
        encrypted_person_id=encrypted_person_id,
        account_id=account_id,
        account_key=account_key,
    )
    client = PGEApiClient(session, auth_manager=auth)
    start, end = _yesterday_hourly_window()
    await client.get_usage(UsageResolution.HOURLY, start, end, account_key)


async def _async_discover_billing_ids(
    hass: HomeAssistant,
    *,
    token: str,
    encrypted_person_id: str,
    account_id: str,
    account_key: str,
    token_expires_at: datetime | None = None,
) -> dict[str, str]:
    """Best-effort AccountDetail discovery for encrypted billing identity ids.

    Failures are swallowed: usage setup must not depend on billing discovery.
    Prefer AccountDetail ciphertexts over getAccountInfo group defaults.
    """
    try:
        session = aiohttp_client.async_get_clientsession(hass)
        auth = PGEAuthManager(
            token=token,
            encrypted_person_id=encrypted_person_id,
            account_id=account_id,
            account_key=account_key,
            token_expires_at=token_expires_at,
        )
        client = PGEBillingApiClient(session, auth)
        snapshot = await client.get_account_detail(account_id)
    except Exception:  # noqa: BLE001 - soft-fail discovery
        _LOGGER.debug("Billing identity discovery skipped", exc_info=True)
        return {}
    out: dict[str, str] = {}
    if snapshot.encrypted_account_number:
        out[CONF_ENCRYPTED_ACCOUNT_NUMBER] = snapshot.encrypted_account_number
    if snapshot.encrypted_person_id:
        out[CONF_ENCRYPTED_PERSON_ID] = snapshot.encrypted_person_id
    if snapshot.encrypted_premise_id:
        out[CONF_ENCRYPTED_PREMISE_ID] = snapshot.encrypted_premise_id
    if snapshot.encrypted_sa_id:
        out[CONF_ENCRYPTED_SA_ID] = snapshot.encrypted_sa_id
    return out


class PGEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._token: str | None = None
        self._encrypted_person_id: str | None = None
        self._account_id: str | None = None
        self._account_key: str | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._refresh_credential: str | None = None
        self._token_expires_at: datetime | None = None
        self._auth_mode = AUTH_MODE_CREDENTIAL
        self._accounts: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return PGEOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_credential(user_input)

    async def async_step_credential(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            self._auth_mode = AUTH_MODE_CREDENTIAL
            provided_account = _normalize_account_id(str(user_input.get(CONF_ACCOUNT_ID, "")))
            try:
                result = await portal_auth.async_login_or_refresh(
                    email=self._email,
                    password=self._password,
                    refresh_credential=None,
                )
            except PGEMfaUnsupportedError:
                errors["base"] = "mfa_unsupported"
            except PGECaptchaUnsupportedError:
                errors["base"] = "captcha_unsupported"
            except PGEDiscoveryIncompleteError:
                errors["base"] = "discovery_incomplete"
            except PGEAuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception during credential setup")
                errors["base"] = "unknown"
            else:
                self._token = result.access_token
                self._encrypted_person_id = result.encrypted_person_id or ""
                self._refresh_credential = result.refresh_credential
                self._token_expires_at = result.expires_at
                self._accounts = result.account_ids
                resolved = _resolve_discovered_account_id(provided_account, self._accounts)
                if resolved is None:
                    errors["base"] = "account_not_found" if self._accounts else "no_accounts"
                else:
                    self._account_id = resolved
                    self._account_key = generate_immutable_account_key()
                    try:
                        return await self._async_finish_credential_entry()
                    except PGEAuthenticationError:
                        errors["base"] = "invalid_auth"
                    except (PGEConnectionError, ValueError):
                        errors["base"] = "cannot_connect"
                    except Exception:
                        _LOGGER.exception("Unexpected exception validating selected account")
                        errors["base"] = "unknown"

        return self.async_show_form(
            step_id="credential",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._auth_mode = AUTH_MODE_CREDENTIAL
        self._account_id = entry_data.get(CONF_ACCOUNT_ID)
        self._account_key = entry_data.get(CONF_ACCOUNT_KEY)
        self._encrypted_person_id = entry_data.get(CONF_ENCRYPTED_PERSON_ID)
        return await self.async_step_reauth_credential()

    async def async_step_reauth_credential(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await portal_auth.async_login_or_refresh(
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    refresh_credential=None,
                )
            except PGEMfaUnsupportedError:
                errors["base"] = "mfa_unsupported"
            except PGECaptchaUnsupportedError:
                errors["base"] = "captcha_unsupported"
            except PGEDiscoveryIncompleteError:
                errors["base"] = "discovery_incomplete"
            except PGEAuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception during credential reauth")
                errors["base"] = "unknown"
            else:
                entry = self._get_reauth_entry()
                update_data = {
                    **entry.data,
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_BEARER_TOKEN: result.access_token,
                    CONF_AUTH_MODE: AUTH_MODE_CREDENTIAL,
                }
                if result.encrypted_person_id:
                    update_data[CONF_ENCRYPTED_PERSON_ID] = result.encrypted_person_id
                if result.expires_at is not None:
                    update_data[CONF_TOKEN_EXPIRES_AT] = result.expires_at.isoformat()
                if result.refresh_credential:
                    update_data[CONF_REFRESH_CREDENTIAL] = result.refresh_credential
                if user_input.get(CONF_PASSWORD):
                    update_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                billing_ids = await _async_discover_billing_ids(
                    self.hass,
                    token=result.access_token,
                    encrypted_person_id=result.encrypted_person_id or update_data.get(CONF_ENCRYPTED_PERSON_ID, ""),
                    account_id=str(entry.data.get(CONF_ACCOUNT_ID, "")),
                    account_key=str(entry.data.get(CONF_ACCOUNT_KEY, "")),
                    token_expires_at=result.expires_at,
                )
                update_data.update(billing_ids)
                # Never change account_key / unique id on reauth.
                self.hass.config_entries.async_update_entry(entry, data=update_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_credential",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    async def _async_finish_credential_entry(self) -> FlowResult:
        assert self._email is not None
        assert self._token is not None
        assert self._account_id is not None
        assert self._account_key is not None
        assert self._encrypted_person_id is not None

        await _validate_usage_for_account(
            self.hass,
            token=self._token,
            encrypted_person_id=self._encrypted_person_id,
            account_id=self._account_id,
            account_key=self._account_key,
        )
        billing_ids = await _async_discover_billing_ids(
            self.hass,
            token=self._token,
            encrypted_person_id=self._encrypted_person_id,
            account_id=self._account_id,
            account_key=self._account_key,
            token_expires_at=self._token_expires_at,
        )
        await self.async_set_unique_id(_account_unique_id(self._account_id))
        self._abort_if_unique_id_configured()
        return self._create_entry(billing_ids=billing_ids)

    def _create_entry(self, *, billing_ids: dict[str, str] | None = None) -> FlowResult:
        assert self._account_id is not None
        assert self._account_key is not None
        assert self._email is not None
        data: dict[str, Any] = {
            CONF_AUTH_MODE: AUTH_MODE_CREDENTIAL,
            CONF_ACCOUNT_ID: self._account_id,
            CONF_ACCOUNT_KEY: self._account_key,
            CONF_ENCRYPTED_PERSON_ID: self._encrypted_person_id,
            CONF_BEARER_TOKEN: self._token,
            CONF_EMAIL: self._email,
        }
        if self._token_expires_at is not None:
            data[CONF_TOKEN_EXPIRES_AT] = self._token_expires_at.isoformat()
        if self._refresh_credential:
            data[CONF_REFRESH_CREDENTIAL] = self._refresh_credential
        if self._password:
            # Keep password as fallback when Cognito refresh expires/fails.
            data[CONF_PASSWORD] = self._password
        if billing_ids:
            data.update(billing_ids)

        return self.async_create_entry(
            title=pge_display_name(self._account_id),
            data=data,
        )


def _options_schema(entry: config_entries.ConfigEntry) -> vol.Schema:
    history_mode = get_entry_option(entry, CONF_HISTORY_MODE, DEFAULT_HISTORY_MODE)
    history_mode_value = history_mode.value if isinstance(history_mode, HistoryMode) else str(history_mode)
    polling_value, polling_unit = resolve_polling_interval_form_defaults(entry)
    return vol.Schema(
        {
            vol.Required(
                CONF_POLLING_INTERVAL,
                default=polling_value,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=365,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_POLLING_INTERVAL_UNIT,
                default=polling_unit,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=PollingIntervalUnit.MINUTES.value, label="minutes"),
                        SelectOptionDict(value=PollingIntervalUnit.HOURS.value, label="hours"),
                        SelectOptionDict(value=PollingIntervalUnit.DAYS.value, label="days"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SYNC_LOCAL_TIME,
                default=resolve_sync_local_time(entry),
            ): TimeSelector(),
            vol.Required(
                CONF_CORRECTION_WINDOW,
                default=int(get_entry_option(entry, CONF_CORRECTION_WINDOW, DEFAULT_CORRECTION_WINDOW)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_CORRECTION_WINDOW,
                    max=MAX_CORRECTION_WINDOW,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="days",
                )
            ),
            vol.Required(
                CONF_HISTORY_MODE,
                default=history_mode_value,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=HistoryMode.FULL.value, label="Full history"),
                        SelectOptionDict(value=HistoryMode.START_DATE.value, label="From start date"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_HISTORY_START_DATE,
                default=get_entry_option(entry, CONF_HISTORY_START_DATE, DEFAULT_HISTORY_FLOOR_ISO)
                or DEFAULT_HISTORY_FLOOR_ISO,
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.DATE)),
            vol.Required(
                CONF_HOURLY_BACKFILL_DAYS,
                default=int(get_entry_option(entry, CONF_HOURLY_BACKFILL_DAYS, DEFAULT_HOURLY_BACKFILL_DAYS)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=3650,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="days",
                )
            ),
            vol.Required(
                CONF_AUTO_BACKFILL,
                default=bool(get_entry_option(entry, CONF_AUTO_BACKFILL, DEFAULT_AUTO_BACKFILL)),
            ): BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_COST,
                default=bool(get_entry_option(entry, CONF_INCLUDE_COST, DEFAULT_INCLUDE_COST)),
            ): BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_DIAGNOSTICS,
                default=bool(get_entry_option(entry, CONF_INCLUDE_DIAGNOSTICS, DEFAULT_INCLUDE_DIAGNOSTICS)),
            ): BooleanSelector(),
            vol.Required(
                CONF_CAPTURE_GRAPHQL_DIAGNOSTICS,
                default=bool(
                    get_entry_option(
                        entry,
                        CONF_CAPTURE_GRAPHQL_DIAGNOSTICS,
                        DEFAULT_CAPTURE_GRAPHQL_DIAGNOSTICS,
                    )
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_BILLING,
                default=bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)),
            ): BooleanSelector(),
            vol.Required(
                CONF_DOWNLOAD_BILL_PDFS,
                default=bool(get_entry_option(entry, CONF_DOWNLOAD_BILL_PDFS, DEFAULT_DOWNLOAD_BILL_PDFS)),
            ): BooleanSelector(),
            vol.Required(
                CONF_BILL_PDF_FORM,
                default=str(get_entry_option(entry, CONF_BILL_PDF_FORM, DEFAULT_BILL_PDF_FORM)),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="detailed", label="Detailed"),
                        SelectOptionDict(value="simplified", label="Simplified"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BILL_PDF_RETENTION,
                default=str(get_entry_option(entry, CONF_BILL_PDF_RETENTION, DEFAULT_BILL_PDF_RETENTION)),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="latest", label="Latest statement only"),
                        SelectOptionDict(value="all_imported", label="All imported bills"),
                        SelectOptionDict(value="rolling_n", label="Rolling count"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BILL_PDF_ROLLING_COUNT,
                default=int(get_entry_option(entry, CONF_BILL_PDF_ROLLING_COUNT, DEFAULT_BILL_PDF_ROLLING_COUNT)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=120,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_BACKFILL_CONCURRENCY,
                default=int(get_entry_option(entry, CONF_BACKFILL_CONCURRENCY, DEFAULT_BACKFILL_CONCURRENCY)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=MAX_BACKFILL_CONCURRENCY,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _panel_options_schema(settings: PanelSettings) -> vol.Schema:
    """Build the Panel settings form schema from current Store values."""
    return vol.Schema(
        {
            vol.Required(CONF_SHOW_SIDEBAR, default=settings.show_sidebar): BooleanSelector(),
            vol.Required(
                CONF_SIDEBAR_TITLE,
                default=settings.sidebar_title,
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(
                CONF_SIDEBAR_ICON,
                default=settings.sidebar_icon,
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_REQUIRE_ADMIN, default=settings.require_admin): BooleanSelector(),
            vol.Required(
                CONF_DEFAULT_SECTION,
                default=settings.default_section,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=value, label=PANEL_SECTION_LABELS[value])
                        for value in PANEL_DEFAULT_SECTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class PGEOptionsFlow(config_entries.OptionsFlow):
    """Configure sync settings and optionally update credentials."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "panel", "credentials", "manual_sync"],
        )

    async def async_step_panel(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Integration-wide panel chrome (domain Store; does not touch entry options)."""
        errors: dict[str, str] = {}
        previous = await async_load_panel_settings(self.hass)

        if user_input is not None:
            try:
                candidate = normalize_panel_settings(user_input, strict=True)
            except PanelSettingsValidationError as err:
                errors.update(err.errors)
            else:
                try:
                    await async_save_panel_settings(self.hass, candidate)
                    await async_apply_panel(self.hass, candidate)
                except Exception:
                    _LOGGER.exception("Failed to update PGE panel settings")
                    try:
                        await async_save_panel_settings(self.hass, previous)
                        await async_apply_panel(self.hass, previous)
                    except Exception:
                        _LOGGER.exception("Failed to restore previous PGE panel settings")
                    errors["base"] = "panel_update_failed"
                else:
                    return self.async_abort(reason="panel_updated")

        if user_input is not None and errors:
            current = normalize_panel_settings(
                {**previous.as_dict(), **user_input},
                strict=False,
            )
        else:
            current = previous

        return self.async_show_form(
            step_id="panel",
            data_schema=_panel_options_schema(current),
            errors=errors,
        )

    async def async_step_manual_sync(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # Imported here only to break package↔config_flow import cycles at module load.
        import custom_components.pge_energy as pge_pkg

        entry = self.config_entry
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        path = None
        if coordinator is not None:
            path = pge_pkg.async_device_progress_path(self.hass, coordinator.account_key)
        link = f"[View progress]({path})" if path else "Open the PGE device page to view progress."

        if coordinator is not None and coordinator.sync_job_in_progress:
            snap = coordinator.sync_progress
            return self.async_abort(
                reason="sync_busy",
                description_placeholders={
                    "status": snap.status,
                    "detail": snap.message or snap.status,
                    "link": link,
                },
            )

        errors: dict[str, str] = {}
        if user_input is not None:
            action = str(user_input[CONF_MANUAL_SYNC_ACTION])
            if action == MANUAL_SYNC_ACTION_REFRESH:
                err = await pge_pkg.async_start_manual_refresh(self.hass, entry.entry_id)
            elif action == MANUAL_SYNC_ACTION_BACKFILL:
                err = await pge_pkg.async_start_history_backfill(self.hass, entry.entry_id)
            else:
                err = "unknown"
            if err == "busy":
                errors["base"] = "sync_busy"
            elif err:
                errors["base"] = "sync_start_failed"
            else:
                # Abort (do not create_entry) so OptionsFlow does not reload the entry
                # and cancel the background sync job.
                return self.async_abort(
                    reason="sync_started",
                    description_placeholders={"link": link},
                )

        return self.async_show_form(
            step_id="manual_sync",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MANUAL_SYNC_ACTION,
                        default=MANUAL_SYNC_ACTION_REFRESH,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=MANUAL_SYNC_ACTION_REFRESH,
                                    label="Refresh now",
                                ),
                                SelectOptionDict(
                                    value=MANUAL_SYNC_ACTION_BACKFILL,
                                    label="Backfill missing history",
                                ),
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"link": link},
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mode = str(user_input[CONF_HISTORY_MODE])
            start_date = user_input.get(CONF_HISTORY_START_DATE)
            if mode == HistoryMode.START_DATE.value:
                if not start_date:
                    errors["base"] = "history_start_required"
                else:
                    try:
                        datetime.fromisoformat(str(start_date))
                    except ValueError:
                        errors["base"] = "invalid_history_start"
            if not errors:
                unit = str(user_input[CONF_POLLING_INTERVAL_UNIT])
                # Validate conversion (also clamps to MIN_POLLING_INTERVAL minutes).
                polling_interval_to_minutes(user_input[CONF_POLLING_INTERVAL], unit)
                sync_raw = str(user_input.get(CONF_SYNC_LOCAL_TIME, DEFAULT_SYNC_LOCAL_TIME))
                sync_hour, sync_minute = parse_sync_local_time(sync_raw)
                options = {
                    CONF_POLLING_INTERVAL: int(user_input[CONF_POLLING_INTERVAL]),
                    CONF_POLLING_INTERVAL_UNIT: unit,
                    CONF_SYNC_LOCAL_TIME: f"{sync_hour:02d}:{sync_minute:02d}:00",
                    CONF_CORRECTION_WINDOW: int(user_input[CONF_CORRECTION_WINDOW]),
                    CONF_HISTORY_MODE: mode,
                    CONF_HISTORY_START_DATE: str(start_date) if start_date else None,
                    CONF_HOURLY_BACKFILL_DAYS: int(user_input[CONF_HOURLY_BACKFILL_DAYS]),
                    CONF_AUTO_BACKFILL: bool(user_input[CONF_AUTO_BACKFILL]),
                    CONF_INCLUDE_COST: bool(user_input[CONF_INCLUDE_COST]),
                    CONF_INCLUDE_DIAGNOSTICS: bool(user_input[CONF_INCLUDE_DIAGNOSTICS]),
                    CONF_CAPTURE_GRAPHQL_DIAGNOSTICS: bool(
                        user_input.get(
                            CONF_CAPTURE_GRAPHQL_DIAGNOSTICS,
                            DEFAULT_CAPTURE_GRAPHQL_DIAGNOSTICS,
                        )
                    ),
                    CONF_INCLUDE_BILLING: bool(user_input.get(CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)),
                    CONF_DOWNLOAD_BILL_PDFS: bool(user_input.get(CONF_DOWNLOAD_BILL_PDFS, DEFAULT_DOWNLOAD_BILL_PDFS)),
                    CONF_BILL_PDF_FORM: str(user_input.get(CONF_BILL_PDF_FORM, DEFAULT_BILL_PDF_FORM)),
                    CONF_BILL_PDF_RETENTION: str(user_input.get(CONF_BILL_PDF_RETENTION, DEFAULT_BILL_PDF_RETENTION)),
                    CONF_BILL_PDF_ROLLING_COUNT: int(
                        user_input.get(CONF_BILL_PDF_ROLLING_COUNT, DEFAULT_BILL_PDF_ROLLING_COUNT)
                    ),
                    CONF_BACKFILL_CONCURRENCY: int(user_input[CONF_BACKFILL_CONCURRENCY]),
                }
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="settings",
            data_schema=_options_schema(self.config_entry),
            errors=errors,
        )

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        account_id = str(entry.data.get(CONF_ACCOUNT_ID, ""))
        if user_input is not None:
            try:
                result = await portal_auth.async_login_or_refresh(
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    refresh_credential=None,
                )
            except PGEMfaUnsupportedError:
                errors["base"] = "mfa_unsupported"
            except PGECaptchaUnsupportedError:
                errors["base"] = "captcha_unsupported"
            except PGEDiscoveryIncompleteError:
                errors["base"] = "discovery_incomplete"
            except PGEAuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception during options credential update")
                errors["base"] = "unknown"
            else:
                update_data = {
                    **entry.data,
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_BEARER_TOKEN: result.access_token,
                    CONF_AUTH_MODE: AUTH_MODE_CREDENTIAL,
                }
                if result.encrypted_person_id:
                    update_data[CONF_ENCRYPTED_PERSON_ID] = result.encrypted_person_id
                if result.expires_at is not None:
                    update_data[CONF_TOKEN_EXPIRES_AT] = result.expires_at.isoformat()
                if result.refresh_credential:
                    update_data[CONF_REFRESH_CREDENTIAL] = result.refresh_credential
                if user_input.get(CONF_PASSWORD):
                    # Persist alongside refresh so renew can fall back to password login.
                    update_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                billing_ids = await _async_discover_billing_ids(
                    self.hass,
                    token=result.access_token,
                    encrypted_person_id=result.encrypted_person_id or update_data.get(CONF_ENCRYPTED_PERSON_ID, ""),
                    account_id=account_id,
                    account_key=str(entry.data.get(CONF_ACCOUNT_KEY, "")),
                    token_expires_at=result.expires_at,
                )
                update_data.update(billing_ids)
                # Never change account_id / account_key / unique_id from options.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data=update_data,
                    title=pge_display_name(account_id),
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="credentials_updated")

        email_default = str(entry.data.get(CONF_EMAIL) or "")
        password_default = str(entry.data.get(CONF_PASSWORD) or "")
        password_stored = bool(password_default)
        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_ID, default=account_id): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT, read_only=True)
                    ),
                    vol.Required(CONF_EMAIL, default=email_default): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    ),
                    # Prefill stored password so the field shows dots and the
                    # reveal control can show the saved value when toggled.
                    vol.Required(CONF_PASSWORD, default=password_default): _PASSWORD_SELECTOR,
                }
            ),
            description_placeholders={
                "account_id": account_id,
                "password_status": (
                    "Password is saved and pre-filled below (masked). Use the eye icon to reveal or edit it."
                    if password_stored
                    else "Enter the PGE account password. After submit it stays saved and will be pre-filled next time."
                ),
            },
            errors=errors,
        )
