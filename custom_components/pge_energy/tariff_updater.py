"""Domain-global on-device tariff updater coordinator.

Discovers, fetches, validates, and persists official PGE TOD and Basic rate
rows from public unauthenticated sources.  Runs independently of Cognito/Apigee
portal auth — no password login is triggered.

The coordinator:
- Checks every 24h with conditional requests (ETag/Last-Modified).
- Honors persisted ``next_retry`` across restarts.
- Discovers Standard Service price summaries and tariff update announcements.
- Processes all unseen documents to catch up after offline periods.
- Schedules an in-process wake at future effective dates.
- Exposes a manual ``pge_energy.refresh_tariffs`` service.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .tariff_sources import (
    _PDF_ALLOWED_HOSTS,
    _PDF_MAX_BYTES,
    _TARIFF_PAGE_DATA_URL,
    _TOD_PAGE_DATA_URL,
    BasicSourceResult,
    TariffFetchError,
    TariffSourceUpdate,
    TodSourceResult,
    discover_tariff_documents,
    parse_price_summary_pdf,
    parse_tod_page_data,
)
from .tariff_store import (
    TariffStoreData,
    async_load_tariff_catalogs,
    async_save_tariff_catalogs,
)
from .time_util import PGE_TZ
from .tod_tariff import (
    BasicComparisonRow,
    TodTariffRow,
    _safe_ymd_date,
    bundled_basic_rows,
    bundled_tod_rows,
    merge_validated_catalog,
    validate_basic_catalog,
    validate_tod_catalog,
)

_LOGGER = logging.getLogger(__name__)

_SERVICE_REFRESH = "refresh_tariffs"

# Retry backoff: 1h → 4h → 12h → 24h.
_RETRY_DELTAS = [
    timedelta(hours=1),
    timedelta(hours=4),
    timedelta(hours=12),
    timedelta(hours=24),
]


def _jittered_delay(base: timedelta) -> timedelta:
    """Add 10% jitter to a delay to avoid thundering herds."""
    jitter = base.total_seconds() * 0.1 * random.random()
    return timedelta(seconds=base.total_seconds() + jitter)


def _is_pdf_url(url: str) -> bool:
    """Check if URL points to an allowed PDF host."""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in _PDF_ALLOWED_HOSTS
    except Exception:
        return False


class TariffUpdaterCoordinator(DataUpdateCoordinator[TariffSourceUpdate]):
    """One domain-global coordinator regardless of account count."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} tariff updater",
            update_interval=None,  # Timing managed by _timer / _schedule_first_check
        )
        self._store_data = TariffStoreData()
        self._tod_rows: list[TodTariffRow] = []
        self._basic_rows: list[BasicComparisonRow] = []
        self._loaded = False
        self._entry_count = 0
        self._timer: asyncio.TimerHandle | None = None
        self._wake_timer: asyncio.TimerHandle | None = None
        self._failure_count: int = 0
        self._processed_pdf_urls: set[str] = set()

    # -- public state --

    @property
    def tod_rows(self) -> list[TodTariffRow]:
        return list(self._tod_rows)

    @property
    def basic_rows(self) -> list[BasicComparisonRow]:
        return list(self._basic_rows)

    @property
    def store_data(self) -> TariffStoreData:
        return self._store_data

    @property
    def is_stale(self) -> bool:
        if not self._store_data.last_success:
            return True
        try:
            last = datetime.fromisoformat(self._store_data.last_success)
            return (datetime.now(UTC) - last) > timedelta(days=3)
        except (ValueError, TypeError):
            return True

    # -- lifecycle --

    async def async_load(self) -> None:
        """Load catalogs from Store before the first poll."""
        if self._loaded:
            return
        self._tod_rows, self._basic_rows, self._store_data = await async_load_tariff_catalogs(self.hass)
        self._loaded = True
        _LOGGER.debug(
            "Loaded tariff catalogs: %d TOD rows, %d Basic rows",
            len(self._tod_rows),
            len(self._basic_rows),
        )

    async def async_start(self, entry: ConfigEntry) -> None:
        """Register coordinator and service on first entry load."""
        self._entry_count += 1
        if self._entry_count == 1:
            await self.async_load()
            # Register the manual refresh service.
            if not self.hass.services.has_service(DOMAIN, _SERVICE_REFRESH):
                self.hass.services.async_register(DOMAIN, _SERVICE_REFRESH, self._handle_refresh_service)
            # Schedule the first check with jitter.
            self._schedule_first_check()

    async def async_stop(self, entry: ConfigEntry) -> None:
        """Unregister when the last entry unloads."""
        self._entry_count -= 1
        if self._entry_count <= 0:
            self._entry_count = 0
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._wake_timer is not None:
                self._wake_timer.cancel()
                self._wake_timer = None
            if self.hass.services.has_service(DOMAIN, _SERVICE_REFRESH):
                self.hass.services.async_remove(DOMAIN, _SERVICE_REFRESH)
            # Shut down DataUpdateCoordinator internal scheduling
            await self.async_shutdown()

    def _schedule_first_check(self) -> None:
        """Schedule first check honoring persisted next_retry."""
        next_check = self._store_data.next_retry
        if next_check:
            try:
                next_dt = datetime.fromisoformat(next_check)
                delay = max(0.0, (next_dt - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError):
                delay = _jittered_delay(timedelta(minutes=30)).total_seconds()
        else:
            delay = _jittered_delay(timedelta(minutes=30)).total_seconds()

        if self._timer is not None:
            self._timer.cancel()
        self._timer = self.hass.loop.call_later(delay, self._on_check_timer)

    def _on_check_timer(self) -> None:
        self._timer = None
        self.hass.async_create_task(self.async_request_refresh())

    def _on_wake_timer(self) -> None:
        self._wake_timer = None
        self.hass.async_create_task(self.async_request_refresh())

    async def _handle_refresh_service(self, call: ServiceCall) -> None:
        """Handle pge_energy.refresh_tariffs service call."""
        await self.async_request_refresh()

    # -- data fetch --

    async def _async_update_data(self) -> TariffSourceUpdate:
        now_iso = datetime.now(UTC).isoformat()
        self._store_data.last_attempt = now_iso

        try:
            update = await self._fetch_and_validate()
        except Exception as exc:
            self._store_data.last_error = str(exc)[:200]
            self._advance_retry()
            self._schedule_first_check()
            _LOGGER.warning("Tariff source check failed: %s", exc)
            raise UpdateFailed(str(exc)) from exc

        # If all sources failed, treat as failure so retry backoff works
        has_tod = update.tod_result and update.tod_result.rows
        has_basic = update.basic_result and update.basic_result.rows
        if not has_tod and not has_basic and update.fetch_errors:
            err_summary = "; ".join(e.reason for e in update.fetch_errors[:3])
            self._store_data.last_error = err_summary[:200]
            self._advance_retry()
            self._schedule_first_check()
            _LOGGER.warning("All tariff sources failed: %s", err_summary)
            raise UpdateFailed(err_summary)

        # Apply successful results
        if has_tod:
            new_tod = merge_validated_catalog(bundled_tod_rows(), self._tod_rows, update.tod_result.rows)
            if not validate_tod_catalog(new_tod):
                self._tod_rows = new_tod
            else:
                _LOGGER.warning("Merged TOD catalog failed validation, keeping previous")

        if has_basic:
            new_basic = merge_validated_catalog(bundled_basic_rows(), self._basic_rows, update.basic_result.rows)
            if not validate_basic_catalog(new_basic):
                self._basic_rows = new_basic
            else:
                _LOGGER.warning("Merged Basic catalog failed validation, keeping previous")

        # Persist
        self._store_data.last_success = now_iso
        self._failure_count = 0  # Reset backoff on success
        if update.fetch_errors:
            self._store_data.last_error = f"{len(update.fetch_errors)} source(s) failed"
        else:
            self._store_data.last_error = None
        self._store_data.next_retry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        await async_save_tariff_catalogs(self.hass, self._tod_rows, self._basic_rows, self._store_data)

        # Schedule wake-up at future effective dates
        self._schedule_effective_date_wakes()

        # Ensure periodic retry timer is always scheduled after success
        if self._timer is None:
            self._schedule_first_check()

        # Emit typed event on new activation
        if has_tod:
            self.hass.bus.async_fire(
                f"{DOMAIN}_tariff_update",
                {
                    "kind": "tod",
                    "rows_activated": len(update.tod_result.rows),
                    "effective_dates": [r.effective_from for r in update.tod_result.rows],
                },
            )
        if has_basic:
            self.hass.bus.async_fire(
                f"{DOMAIN}_tariff_update",
                {
                    "kind": "basic",
                    "rows_activated": len(update.basic_result.rows),
                    "effective_dates": [r.effective_from for r in update.basic_result.rows],
                },
            )

        return update

    async def _fetch_and_validate(self) -> TariffSourceUpdate:
        """Fetch all public sources and parse them."""
        errors: list[TariffFetchError] = []
        tod_result: TodSourceResult | None = None
        basic_result: BasicSourceResult | None = None

        session = aiohttp_client.async_get_clientsession(self.hass)
        # 1. Fetch TOD page-data
        tod_result, tod_error = await self._fetch_tod_page_data(session)
        if tod_error:
            errors.append(tod_error)

        # 2. Fetch tariff page-data for document discovery
        tariff_docs, tariff_error = await self._fetch_tariff_documents(session)
        if tariff_error:
            errors.append(tariff_error)

        # 3. Process discovered documents
        if tariff_docs:
            basic_result = await self._process_tariff_documents(session, tariff_docs, errors)

        return TariffSourceUpdate(
            tod_result=tod_result,
            basic_result=basic_result,
            fetch_errors=errors,
        )

    async def _fetch_tod_page_data(
        self, session: aiohttp.ClientSession
    ) -> tuple[TodSourceResult | None, TariffFetchError | None]:
        """Fetch and parse the TOD page-data JSON."""
        etag = self._store_data.etag_map.get(_TOD_PAGE_DATA_URL)
        last_mod = self._store_data.last_modified_map.get(_TOD_PAGE_DATA_URL)

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_mod:
            headers["If-Modified-Since"] = last_mod

        try:
            async with session.get(
                _TOD_PAGE_DATA_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 304:
                    _LOGGER.debug("TOD page-data: 304 Not Modified")
                    return None, None
                if resp.status != 200:
                    return None, TariffFetchError(
                        url=_TOD_PAGE_DATA_URL,
                        reason=f"HTTP {resp.status}",
                        status_code=resp.status,
                    )
                data = await resp.json()
                # Store freshness
                new_etag = resp.headers.get("ETag")
                new_lm = resp.headers.get("Last-Modified")
                if new_etag:
                    self._store_data.etag_map[_TOD_PAGE_DATA_URL] = new_etag
                if new_lm:
                    self._store_data.last_modified_map[_TOD_PAGE_DATA_URL] = new_lm

                result = parse_tod_page_data(data)
                if not result.rows and result.errors:
                    return None, TariffFetchError(
                        url=_TOD_PAGE_DATA_URL,
                        reason=f"Parse errors: {'; '.join(result.errors[:3])}",
                    )
                return result, None
        except Exception as exc:
            return None, TariffFetchError(url=_TOD_PAGE_DATA_URL, reason=str(exc)[:200])

    async def _fetch_tariff_documents(
        self, session: aiohttp.ClientSession
    ) -> tuple[list[dict[str, Any]] | None, TariffFetchError | None]:
        """Fetch tariff page-data and extract document list."""
        etag = self._store_data.etag_map.get(_TARIFF_PAGE_DATA_URL)
        last_mod = self._store_data.last_modified_map.get(_TARIFF_PAGE_DATA_URL)

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_mod:
            headers["If-Modified-Since"] = last_mod

        try:
            async with session.get(
                _TARIFF_PAGE_DATA_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 304:
                    return None, None
                if resp.status != 200:
                    return None, TariffFetchError(
                        url=_TARIFF_PAGE_DATA_URL,
                        reason=f"HTTP {resp.status}",
                        status_code=resp.status,
                    )
                data = await resp.json()
                new_etag = resp.headers.get("ETag")
                new_lm = resp.headers.get("Last-Modified")
                if new_etag:
                    self._store_data.etag_map[_TARIFF_PAGE_DATA_URL] = new_etag
                if new_lm:
                    self._store_data.last_modified_map[_TARIFF_PAGE_DATA_URL] = new_lm

                docs = discover_tariff_documents(data)
                return docs, None
        except Exception as exc:
            return None, TariffFetchError(url=_TARIFF_PAGE_DATA_URL, reason=str(exc)[:200])

    async def _process_tariff_documents(
        self,
        session: aiohttp.ClientSession,
        docs: list[dict[str, Any]],
        errors: list[TariffFetchError],
    ) -> BasicSourceResult:
        """Download and parse unseen Standard Service PDFs."""
        basic_rows: list[BasicComparisonRow] = []
        seen_urls: list[str] = []
        parse_errors: list[str] = []

        for doc in docs:
            url = doc.get("url", "")
            title = doc.get("title", "")
            eff_date = doc.get("effective_date_str", "")
            kind = doc.get("kind", "")

            if not url or not _is_pdf_url(url):
                continue

            # Skip if we already processed this URL in this session
            if url in self._processed_pdf_urls:
                continue

            # Only process price summaries for Basic comparison
            if kind != "price_summary":
                continue

            # Download PDF
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True,
                ) as resp:
                    # Validate final URL after redirects stays on allowed host
                    resp_host = getattr(resp.url, "hostname", None)
                    if resp_host and resp_host not in _PDF_ALLOWED_HOSTS:
                        errors.append(TariffFetchError(url=url, reason=f"Redirected to disallowed host: {resp_host}"))
                        continue
                    if resp.status != 200:
                        errors.append(TariffFetchError(url=url, reason=f"HTTP {resp.status}", status_code=resp.status))
                        continue
                    content_type = resp.headers.get("Content-Type", "")
                    if "pdf" not in content_type.lower() and not url.endswith(".pdf"):
                        errors.append(TariffFetchError(url=url, reason=f"Not a PDF: {content_type}"))
                        continue
                    # Stream with size limit to avoid loading huge files into memory
                    chunks: list[bytes] = []
                    total = 0
                    pdf_bytes = None
                    async for chunk in resp.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > _PDF_MAX_BYTES:
                            errors.append(
                                TariffFetchError(
                                    url=url,
                                    reason=f"PDF exceeds {_PDF_MAX_BYTES} bytes",
                                )
                            )
                            break
                        chunks.append(chunk)
                    else:
                        pdf_bytes = b"".join(chunks)
                    if pdf_bytes is None:
                        continue
            except Exception as exc:
                errors.append(TariffFetchError(url=url, reason=str(exc)[:200]))
                continue

            # Parse
            if not eff_date:
                # Try to extract from title
                import re

                date_match = re.search(r"effective\s+(\w+\s+\d{1,2},?\s+\d{4})", title, re.IGNORECASE)
                if date_match:
                    from .tariff_sources import _parse_as_of_date

                    try:
                        eff_date = _parse_as_of_date(date_match.group(1))
                    except ValueError:
                        parse_errors.append(f"Cannot extract effective date from {title}")
                        continue
                else:
                    parse_errors.append(f"No effective date for {title}")
                    continue

            result = parse_price_summary_pdf(pdf_bytes, url, title, eff_date)
            if isinstance(result, TariffFetchError):
                parse_errors.append(f"{result.url}: {result.reason}")
                errors.append(result)
            else:
                basic_rows.append(result)
                seen_urls.append(url)
                self._processed_pdf_urls.add(url)

        return BasicSourceResult(
            rows=basic_rows,
            seen_urls=seen_urls,
            errors=parse_errors,
        )

    def _advance_retry(self) -> None:
        """Advance to next retry delay based on failure count."""
        now = datetime.now(UTC)
        self._failure_count += 1
        # Select backoff step: clamp to max step
        step = min(self._failure_count - 1, len(_RETRY_DELTAS) - 1)
        delta = _RETRY_DELTAS[step]
        self._store_data.next_retry = (now + delta).isoformat()

    def _schedule_effective_date_wakes(self) -> None:
        """Schedule wake at next future effective date."""
        now = datetime.now(UTC)
        today_date = now.astimezone(PGE_TZ).date()
        future_dates: list[str] = []

        for row in self._tod_rows:
            d = _safe_ymd_date(row.effective_from)
            if d is not None and d > today_date:
                future_dates.append(row.effective_from)
        for row in self._basic_rows:
            d = _safe_ymd_date(row.effective_from)
            if d is not None and d > today_date:
                future_dates.append(row.effective_from)

        if not future_dates:
            # No future effective dates — ensure the periodic retry timer is
            # still scheduled so tariff discovery does not stall.
            if self._timer is None and self._store_data.next_retry:
                try:
                    next_dt = datetime.fromisoformat(self._store_data.next_retry)
                    delay = max(0.0, (next_dt - now).total_seconds())
                    if delay > 0:
                        self._timer = self.hass.loop.call_later(delay, self._on_check_timer)
                except (ValueError, TypeError):
                    pass
            return

        next_future = min(future_dates)
        d = _safe_ymd_date(next_future)
        if d is not None:
            pacific_midnight = datetime(
                d.year,
                d.month,
                d.day,
                hour=0,
                minute=0,
                tzinfo=PGE_TZ,
            )
            wake_dt = pacific_midnight.astimezone(UTC)
            delay = max(0.0, (wake_dt - now).total_seconds())
            if delay > 0:
                if self._wake_timer is not None:
                    self._wake_timer.cancel()
                self._wake_timer = self.hass.loop.call_later(delay, self._on_wake_timer)
