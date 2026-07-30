"""REST download and filesystem helpers for PGE bill PDFs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .auth import PGEAuthManager
from .bill_pdf_models import BillPdfFileRecord, BillPdfForm
from .bill_pdf_parser import sha256_pdf, validate_pdf_bytes
from .const import BILL_PDF_API_URL, BILL_PDF_MAX_BYTES
from .exceptions import PGEAuthenticationError, PGEAuthorizationError, PGEConnectionError

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_RETRIES = 3

# Portal-style origin (bill PDF calls originate from the main portal SPA).
_ORIGIN = "https://portlandgeneral.com"
_REFERER = "https://portlandgeneral.com/"

_BILL_PDF_WWW_ROOT = "pge_energy"
_BILLS_SUBDIR = "bills"
_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_(?:detailed|simplified)\.pdf$")


def bill_pdf_form_flags(form: BillPdfForm) -> tuple[bool, bool]:
    """Return REST body flags ``(isSummary, isNonDetailed)`` for ``form``."""
    return False, form == BillPdfForm.SIMPLIFIED


def bill_pdf_relpath(bill_date: str | date, form: BillPdfForm | str) -> str:
    """Return the integration filename ``YYYY-MM-DD_<form>.pdf``."""
    date_str = bill_date.isoformat() if isinstance(bill_date, date) else str(bill_date)
    form_value = form.value if isinstance(form, BillPdfForm) else str(form)
    _validate_bill_date(date_str)
    _validate_form_value(form_value)
    return f"{date_str}_{form_value}.pdf"


def bill_pdf_full_relpath(account_key: str, bill_date: str | date, form: BillPdfForm | str) -> str:
    """Return the ``www/``-relative path stored on ``BillPdfFileRecord.relpath``."""
    _validate_account_key(account_key)
    filename = bill_pdf_relpath(bill_date, form)
    return f"{_BILL_PDF_WWW_ROOT}/{account_key}/{_BILLS_SUBDIR}/{filename}"


def bill_pdf_local_url(relpath: str) -> str:
    """Map a ``www/``-relative path to a Home Assistant ``/local/...`` URL."""
    normalized = relpath.lstrip("/")
    return f"/local/{normalized}"


def validate_bill_pdf_response(data: bytes) -> None:
    """Reject invalid or oversized PDF payloads before write/parse."""
    validate_pdf_bytes(data)


async def async_download_bill_pdf(
    hass: HomeAssistant,
    auth: PGEAuthManager,
    encrypted_bill_id: str,
    form: BillPdfForm,
) -> bytes | None:
    """Download one bill PDF from the portal REST API.

    Returns ``None`` for portal 404/empty/not-found responses. Raises typed PGE
    errors after bounded retries for auth/network failures.
    """
    if not encrypted_bill_id:
        return None

    is_summary, is_non_detailed = bill_pdf_form_flags(form)
    payload = {
        "encryptedBillId": encrypted_bill_id,
        "isSummary": is_summary,
        "isNonDetailed": is_non_detailed,
    }
    session = aiohttp_client.async_get_clientsession(hass)

    renewed = False
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        token = await auth.ensure_valid_token()
        headers = {
            "accept": "application/pdf,*/*",
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "origin": _ORIGIN,
            "referer": _REFERER,
        }
        try:
            async with session.post(
                BILL_PDF_API_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            ) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 401:
                    if not renewed:
                        renewed = True
                        await auth.force_renew()
                        continue
                    raise PGEAuthenticationError("Token expired or invalid")
                if resp.status == 403:
                    raise PGEAuthorizationError("Access forbidden")
                if resp.status in (502, 503, 504):
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise PGEConnectionError(f"HTTP {resp.status} after {MAX_RETRIES} attempts")
                if resp.status != 200:
                    body = await resp.text()
                    _LOGGER.debug(
                        "Bill PDF download failed with HTTP %s (body length %s)",
                        resp.status,
                        len(body),
                    )
                    raise PGEConnectionError(f"HTTP {resp.status}")

                data = await resp.read()
                if not data:
                    return None
                if len(data) > BILL_PDF_MAX_BYTES:
                    raise PGEConnectionError(f"PDF exceeds {BILL_PDF_MAX_BYTES} byte safety limit")
                if not data.startswith(b"%PDF-"):
                    text = data.decode("utf-8", errors="ignore").strip().lower()
                    if not text or "not found" in text:
                        return None
                    raise PGEConnectionError("Response is not a PDF")
                return data
        except (TimeoutError, aiohttp.ClientError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2**attempt)
                continue
            raise PGEConnectionError(f"Connection failed: {exc}") from exc

    raise PGEConnectionError(f"Request failed after {MAX_RETRIES} attempts: {last_exc}")


async def async_write_bill_pdf(
    hass: HomeAssistant,
    account_key: str,
    bill_date: str | date,
    form: BillPdfForm,
    data: bytes,
) -> BillPdfFileRecord:
    """Atomically write validated PDF bytes under ``www/pge_energy/.../bills/``."""
    validate_bill_pdf_response(data)
    filename = bill_pdf_relpath(bill_date, form)
    bills_dir = _bills_dir(hass, account_key)
    await hass.async_add_executor_job(_write_bill_pdf_sync, bills_dir, filename, data)
    return BillPdfFileRecord(
        form=form.value,
        relpath=bill_pdf_full_relpath(account_key, bill_date, form),
        source_sha256=sha256_pdf(data),
        byte_size=len(data),
        page_count=None,
        fetched_at=datetime.now(UTC).isoformat(),
    )


async def async_read_bill_pdf(
    hass: HomeAssistant,
    account_key: str,
    relpath: str,
) -> bytes:
    """Read a retained bill PDF after path traversal checks."""
    path = _resolve_bill_pdf_path(hass, account_key, relpath)
    return await hass.async_add_executor_job(path.read_bytes)


async def async_gc_bill_pdf_files(
    hass: HomeAssistant,
    account_key: str,
    keep_relpaths: set[str],
) -> None:
    """Delete retained PDFs outside ``keep_relpaths`` matching the integration pattern."""
    bills_dir = _bills_dir(hass, account_key)
    await hass.async_add_executor_job(_gc_bill_pdf_files_sync, bills_dir, account_key, keep_relpaths)


def _validate_account_key(account_key: str) -> None:
    if not account_key or "/" in account_key or "\\" in account_key or ".." in account_key:
        raise ValueError("invalid account_key")


def _validate_bill_date(bill_date: str) -> None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", bill_date):
        raise ValueError("invalid bill_date")
    date.fromisoformat(bill_date)


def _validate_form_value(form: str) -> None:
    if form not in {BillPdfForm.DETAILED.value, BillPdfForm.SIMPLIFIED.value}:
        raise ValueError("invalid bill_pdf form")


def _www_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www")).resolve()


def _bills_dir(hass: HomeAssistant, account_key: str) -> Path:
    _validate_account_key(account_key)
    www_root = _www_root(hass)
    bills_dir = (www_root / _BILL_PDF_WWW_ROOT / account_key / _BILLS_SUBDIR).resolve()
    if not str(bills_dir).startswith(str(www_root)):
        raise ValueError("bill PDF path escapes www root")
    return bills_dir


def _resolve_bill_pdf_path(hass: HomeAssistant, account_key: str, relpath: str) -> Path:
    _validate_account_key(account_key)
    filename = Path(relpath).name
    if not _FILENAME_RE.fullmatch(filename):
        raise ValueError("invalid bill PDF relpath")
    expected_relpath = bill_pdf_full_relpath(
        account_key,
        _bill_date_from_filename(filename),
        _form_from_filename(filename),
    )
    if relpath.replace("\\", "/") != expected_relpath:
        raise ValueError("relpath does not match account_key")
    bills_dir = _bills_dir(hass, account_key)
    target = (bills_dir / filename).resolve()
    if not str(target).startswith(str(bills_dir)):
        raise ValueError("bill PDF path escapes bills directory")
    if target.is_symlink():
        raise ValueError("bill PDF symlinks are not allowed")
    if not target.is_file():
        raise FileNotFoundError(filename)
    return target


def _bill_date_from_filename(filename: str) -> str:
    return filename.split("_", 1)[0]


def _form_from_filename(filename: str) -> str:
    stem = filename.removesuffix(".pdf")
    return stem.rsplit("_", 1)[1]


def _write_bill_pdf_sync(bills_dir: Path, filename: str, data: bytes) -> None:
    if not _FILENAME_RE.fullmatch(filename):
        raise ValueError("invalid bill PDF filename")
    bills_dir.mkdir(parents=True, exist_ok=True)
    dest = bills_dir / filename
    fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", dir=str(bills_dir))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, dest)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _gc_bill_pdf_files_sync(
    bills_dir: Path,
    account_key: str,
    keep_relpaths: set[str],
) -> None:
    if not bills_dir.is_dir():
        return
    for entry in bills_dir.iterdir():
        if not entry.is_file() or entry.is_symlink():
            continue
        filename = entry.name
        if not _FILENAME_RE.fullmatch(filename):
            continue
        relpath = bill_pdf_full_relpath(
            account_key,
            _bill_date_from_filename(filename),
            _form_from_filename(filename),
        )
        if relpath in keep_relpaths:
            continue
        with contextlib.suppress(OSError):
            entry.unlink()
