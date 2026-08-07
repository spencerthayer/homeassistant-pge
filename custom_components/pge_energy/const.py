from datetime import date, timedelta
from enum import StrEnum

DOMAIN = "pge_energy"
VERSION = "0.8.0"
PLATFORMS = ["sensor", "binary_sensor"]

# Custom panel (registered once per HA instance, not per entry).
# Default title/icon; Configure → Panel can hide the sidebar link or change chrome.
# Sidebar *order* is owned by HA / Browser Mod (never mutate user-store sidebar keys).
PANEL_URL_PATH = "pge"
PANEL_WEBCOMPONENT = "pge-energy-panel"
PANEL_SIDEBAR_TITLE = "PGE"
PANEL_SIDEBAR_ICON = "mdi:transmission-tower"
FRONTEND_URL_PATH = "/pge_energy_frontend"
BRAND_URL_PATH = "/pge_energy_brand"
PANEL_SETUP_KEY = f"{DOMAIN}_panel_setup"
WS_SETUP_KEY = f"{DOMAIN}_ws_setup"
CONF_BEARER_TOKEN = "bearer_token"
CONF_ENCRYPTED_PERSON_ID = "encrypted_person_id"
CONF_ACCOUNT_ID = "account_id"
CONF_ACCOUNT_KEY = "account_key"
# Encrypted identifiers required for billing/programs GraphQL ops.
CONF_ENCRYPTED_ACCOUNT_NUMBER = "encrypted_account_number"
CONF_ENCRYPTED_PREMISE_ID = "encrypted_premise_id"
CONF_ENCRYPTED_SA_ID = "encrypted_sa_id"
CONF_INCLUDE_BILLING = "include_billing"
DEFAULT_INCLUDE_BILLING = True
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REFRESH_CREDENTIAL = "refresh_credential"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_AUTH_MODE = "auth_mode"
# Apigee bearer tokens are short-lived; renew this far before wall-clock expiry.
TOKEN_EXPIRY_SKEW_SECONDS = 300
AUTH_MODE_CREDENTIAL = "credential"
# Legacy entries only — no longer creatable via config flow.
AUTH_MODE_MANUAL_TOKEN = "manual_token"
CONF_POLLING_INTERVAL = "polling_interval"
CONF_POLLING_INTERVAL_UNIT = "polling_interval_unit"
CONF_SYNC_LOCAL_TIME = "sync_local_time"
CONF_CORRECTION_WINDOW = "correction_window"
CONF_HOURLY_BACKFILL_DAYS = "hourly_backfill_days"
CONF_INCLUDE_COST = "include_cost"
CONF_INCLUDE_DIAGNOSTICS = "include_diagnostics"
CONF_CAPTURE_GRAPHQL_DIAGNOSTICS = "capture_graphql_diagnostics"
CONF_BACKFILL_CONCURRENCY = "backfill_concurrency"
CONF_AUTO_BACKFILL = "auto_backfill"
CONF_HISTORY_MODE = "history_mode"
CONF_HISTORY_START_DATE = "history_start_date"


class HistoryMode(StrEnum):
    FULL = "full"
    START_DATE = "start_date"


class PollingIntervalUnit(StrEnum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


# UI default: every 4 hours on the Pacific clock grid starting at midnight
# (00:00, 04:00, 08:00, 12:00, 16:00, 20:00). Hour- and day-unit polls align to
# sync_local_time; minute units stay a fixed interval (min 15).
DEFAULT_POLLING_INTERVAL = 4
DEFAULT_POLLING_INTERVAL_UNIT = PollingIntervalUnit.HOURS
DEFAULT_SYNC_LOCAL_TIME = "00:00:00"
DEFAULT_SYNC_LOCAL_HOUR = 0  # derived from DEFAULT_SYNC_LOCAL_TIME
MIN_POLLING_INTERVAL = 15
DEFAULT_CORRECTION_WINDOW = 7
MIN_CORRECTION_WINDOW = 2
MAX_CORRECTION_WINDOW = 31
DEFAULT_BACKFILL_CONCURRENCY = 2
MAX_BACKFILL_CONCURRENCY = 4
DEFAULT_HOURLY_BACKFILL_DAYS = 365
DEFAULT_AUTO_BACKFILL = True
DEFAULT_INCLUDE_COST = True
DEFAULT_INCLUDE_DIAGNOSTICS = True
DEFAULT_CAPTURE_GRAPHQL_DIAGNOSTICS = False
DEFAULT_HISTORY_MODE = HistoryMode.FULL
# Matches statistics lookback floor in statistics.py (_async_anchor_sum).
DEFAULT_HISTORY_FLOOR = date(2019, 1, 1)
DEFAULT_HISTORY_FLOOR_ISO = DEFAULT_HISTORY_FLOOR.isoformat()
# Live DAILY ranges under ~31 days hard-error; pad short windows to this length.
MIN_DAILY_REQUEST_DAYS = 31
# MONTHLY billing-period totals parked on month-start. Real residential days stay
# well below these; use them to detect monthly/hourly collisions in `_consumption`.
MONTHLY_LUMP_MIN_KWH = 200.0
MONTHLY_LUMP_MIN_COST = 50.0
# DAILY backfill parks a whole local day on midnight. When hourly arrives for that
# day, drop leftover coarse rows (typical peak hour is well under this).
DAILY_LUMP_MIN_KWH = 12.0
DAILY_LUMP_MIN_COST = 3.0
# When a scheduled poll finds yesterday still incomplete, retry this often until
# hourly validates complete (PGE often publishes after midnight).
CATCHUP_RETRY_HOURS = 2

# Cognito InitiateAuth throttle / password-attempt lockout backoff (shared per email).
# Live probe (2026-07-29): TooManyRequestsException under ~20-way parallel USER_PASSWORD_AUTH;
# no Retry-After header. Password lockout message is NotAuthorizedException
# "Password attempts exceeded" after 5 wrong passwords (AWS exponential lockout, max ~15m).
COGNITO_RATE_LIMIT_UNTIL_KEY = "cognito_rate_limit_until"
COGNITO_RATE_LIMIT_DEFAULT_SECONDS = 60.0
COGNITO_RATE_LIMIT_LOCKOUT_SECONDS = 900.0
COGNITO_RATE_LIMIT_MAX_SECONDS = 900.0

# Backfill hang recovery (progress watchdog + hard release + tier/save bounds).
BACKFILL_STALL_TIMEOUT = timedelta(minutes=30)
BACKFILL_STALL_POLL_SECONDS = 60
BACKFILL_TIER_TIMEOUT = timedelta(hours=2)
BACKFILL_CANCEL_GRACE = 30.0  # seconds to honour cancel before orphaning the task
IMPORT_STATE_SAVE_TIMEOUT = 30.0
# Recorder ack: verify, then re-issue the write on mismatch (dropped import jobs).
STATISTICS_ACK_WRITE_ATTEMPTS = 3
STATISTIC_ID_SUFFIX_CONSUMPTION = "_consumption"
STATISTIC_ID_SUFFIX_RETURN = "_return"
STATISTIC_ID_SUFFIX_COST = "_cost"
STATISTIC_ID_SUFFIX_COMPENSATION = "_compensation"
STATISTIC_ID_SUFFIX_TEMPERATURE = "_temperature"

# Billing / programs long-term statistic id suffixes (external + mirrored).
STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE = "_account_balance"
STATISTIC_ID_SUFFIX_AMOUNT_DUE = "_amount_due"
STATISTIC_ID_SUFFIX_BILL_AMOUNT = "_bill_amount"
STATISTIC_ID_SUFFIX_BILL_KWH = "_bill_kwh"
STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT = "_payment_amount"
STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE = "_bill_avg_temperature"
STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS = "_ytd_program_savings"
STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT = "_last_payment_amount"

# Entity unique-id suffixes (entity_id ≈ sensor.pge_<account>_<name>).
# Long-term history for energy/cost/temperature is mirrored onto these entity
# statistic_ids in addition to external pge_energy:… statistics.
ENTITY_UNIQUE_ENERGY = "energy"
ENTITY_UNIQUE_RETURN = "return"
ENTITY_UNIQUE_COST = "cost"
ENTITY_UNIQUE_COMPENSATION = "compensation"
ENTITY_UNIQUE_TEMPERATURE = "latest_temperature"
ENTITY_UNIQUE_HOURLY_ENERGY = "latest_hourly_energy"
ENTITY_UNIQUE_HOURLY_RETURN = "hourly_return"
ENTITY_UNIQUE_HOURLY_COST = "hourly_cost"
ENTITY_UNIQUE_HOURLY_COMPENSATION = "hourly_compensation"
ENTITY_UNIQUE_YESTERDAY_ENERGY = "yesterday_energy"
ENTITY_UNIQUE_YESTERDAY_RETURN = "yesterday_return"
ENTITY_UNIQUE_YESTERDAY_COST = "yesterday_cost"
ENTITY_UNIQUE_YESTERDAY_COMPENSATION = "yesterday_compensation"
ENTITY_UNIQUE_SYNC_STATUS = "sync_status"
ENTITY_UNIQUE_SYNC_PHASE = "sync_phase"
ENTITY_UNIQUE_SYNC_PROGRESS = "sync_progress"
ENTITY_UNIQUE_SYNC_ETA = "sync_eta"
ENTITY_UNIQUE_SYNC_DETAIL = "sync_detail"
ENTITY_UNIQUE_SYNC_ERROR = "sync_error"

# Billing / programs sensor entity unique-id suffixes.
ENTITY_UNIQUE_ACCOUNT_BALANCE = "account_balance"
ENTITY_UNIQUE_AMOUNT_DUE = "amount_due"
ENTITY_UNIQUE_DUE_DATE = "due_date"
ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT = "last_payment_amount"
ENTITY_UNIQUE_LAST_PAYMENT_DATE = "last_payment_date"
ENTITY_UNIQUE_CURRENT_BILL_AMOUNT = "current_bill_amount"
ENTITY_UNIQUE_CURRENT_BILL_KWH = "current_bill_kwh"
ENTITY_UNIQUE_CURRENT_BILL_START = "current_bill_start"
ENTITY_UNIQUE_CURRENT_BILL_END = "current_bill_end"
ENTITY_UNIQUE_BILL_PREVIOUS_BALANCE = "bill_previous_balance"
ENTITY_UNIQUE_BILL_CURRENT_CHARGES = "bill_current_charges"
ENTITY_UNIQUE_BILL_AVG_TEMPERATURE = "bill_avg_temperature"
ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS = "ytd_program_savings"
ENTITY_UNIQUE_LIFETIME_PAYMENTS = "lifetime_payments"
ENTITY_UNIQUE_LIFETIME_BILLED = "lifetime_billed"
ENTITY_UNIQUE_BILLING_LAST_SYNC = "billing_last_sync"
# Open-cycle estimates from getEnergyTrackerData (portal "Current Use" card).
ENTITY_UNIQUE_EST_CURRENT_CHARGES = "est_current_charges"
ENTITY_UNIQUE_EST_NEXT_BILL_MIN = "est_next_bill_min"
ENTITY_UNIQUE_EST_NEXT_BILL_MAX = "est_next_bill_max"
ENTITY_UNIQUE_BILLING_CYCLE_DAY = "billing_cycle_day"
ENTITY_UNIQUE_BILLING_CYCLE_TOTAL_DAYS = "billing_cycle_total_days"

# Billing / programs binary sensor entity unique-id suffixes.
BINARY_UNIQUE_AUTOPAY = "autopay"
BINARY_UNIQUE_PAPERLESS_BILL = "paperless_bill"
BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES = "program_peak_time_rebates"
BINARY_UNIQUE_PROGRAM_GREEN_FUTURE = "program_green_future"
BINARY_UNIQUE_PROGRAM_TIME_OF_DAY = "program_time_of_day"
BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT = "program_smart_thermostat"
BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT = "program_habitat_support"

SYNC_STATUS_IDLE = "idle"
SYNC_STATUS_REFRESHING = "refreshing"
SYNC_STATUS_BACKFILLING = "backfilling"
SYNC_STATUS_COMPLETE = "complete"
SYNC_STATUS_FAILED = "failed"

SYNC_PHASE_IDLE = "idle"
SYNC_PHASE_CORRECTION = "correction"
SYNC_PHASE_HOURLY = "hourly"
SYNC_PHASE_DAILY = "daily"
SYNC_PHASE_MONTHLY = "monthly"
SYNC_PHASE_BILLING_SNAPSHOT = "billing_snapshot"
SYNC_PHASE_BILLING_HISTORY = "billing_history"
SYNC_PHASE_PROGRAMS = "programs"
SYNC_PHASE_DOWNLOADING_PDFS = "downloading_pdfs"
SYNC_PHASE_PARSING_PDFS = "parsing_pdfs"
SYNC_PHASE_IMPORTING_PDF_STATISTICS = "importing_pdf_statistics"

# Bill PDF download / normalization (opt-in; default off).
CONF_DOWNLOAD_BILL_PDFS = "download_bill_pdfs"
DEFAULT_DOWNLOAD_BILL_PDFS = False
CONF_BILL_PDF_FORM = "bill_pdf_form"
DEFAULT_BILL_PDF_FORM = "detailed"
CONF_BILL_PDF_RETENTION = "bill_pdf_retention"
DEFAULT_BILL_PDF_RETENTION = "latest"
CONF_BILL_PDF_ROLLING_COUNT = "bill_pdf_rolling_count"
DEFAULT_BILL_PDF_ROLLING_COUNT = 12
BILL_PDF_API_URL = "https://apix.portlandgeneral.com/pge-bill-api/pdf/bills"
BILL_PDF_PARSER_VERSION = 1
BILL_PDF_MAX_BYTES = 10 * 1024 * 1024
BILL_PDF_MAX_PAGES = 24

# PDF-derived external statistic id suffixes (distinct from GraphQL billing series).
STATISTIC_ID_SUFFIX_BILL_PDF_AMOUNT_DUE = "_bill_pdf_amount_due"
STATISTIC_ID_SUFFIX_BILL_PDF_TOTAL_KWH = "_bill_pdf_total_kwh"
STATISTIC_ID_SUFFIX_BILL_PDF_PAYMENT_RECEIVED = "_bill_pdf_payment_received"
STATISTIC_ID_SUFFIX_BILL_PDF_BALANCE_FORWARD = "_bill_pdf_balance_forward"
STATISTIC_ID_SUFFIX_BILL_PDF_PREVIOUS_AMOUNT_DUE = "_bill_pdf_previous_amount_due"
STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_DELIVERY_CHARGES = "_bill_pdf_energy_delivery_charges"
STATISTIC_ID_SUFFIX_BILL_PDF_BASIC_CHARGE = "_bill_pdf_basic_charge"
STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_USE_CHARGE = "_bill_pdf_energy_use_charge"
STATISTIC_ID_SUFFIX_BILL_PDF_TRANSMISSION_CHARGE = "_bill_pdf_transmission_charge"
STATISTIC_ID_SUFFIX_BILL_PDF_DISTRIBUTION_CHARGE = "_bill_pdf_distribution_charge"
STATISTIC_ID_SUFFIX_BILL_PDF_POWER_COST_ADJUSTMENT = "_bill_pdf_power_cost_adjustment"
STATISTIC_ID_SUFFIX_BILL_PDF_REGULATORY_ADJUSTMENTS = "_bill_pdf_regulatory_adjustments"
STATISTIC_ID_SUFFIX_BILL_PDF_STATE_PASS_THROUGHS = "_bill_pdf_state_pass_throughs"
STATISTIC_ID_SUFFIX_BILL_PDF_PROGRAM_CHARGES = "_bill_pdf_program_charges"
STATISTIC_ID_SUFFIX_BILL_PDF_GREEN_FUTURE_CHARGE = "_bill_pdf_green_future_charge"
STATISTIC_ID_SUFFIX_BILL_PDF_TAXES_AND_INVESTMENTS = "_bill_pdf_taxes_and_investments"
STATISTIC_ID_SUFFIX_BILL_PDF_LOCAL_TAX = "_bill_pdf_local_tax"
STATISTIC_ID_SUFFIX_BILL_PDF_PUBLIC_PURPOSE_CHARGE = "_bill_pdf_public_purpose_charge"

ENTITY_UNIQUE_BILL_PDF_PARSE_STATUS = "bill_pdf_parse_status"
ENTITY_UNIQUE_BILL_PDF_PREFIX = "bill_pdf_"

CONF_MANUAL_SYNC_ACTION = "manual_sync_action"
MANUAL_SYNC_ACTION_REFRESH = "refresh"
MANUAL_SYNC_ACTION_BACKFILL = "backfill"

GRAPHQL_URL = "https://apix.portlandgeneral.com/pge-graphql"
OPERATION_NAME = "GetUsageCompare"
