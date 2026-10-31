"""Join PGE Apigee paths to the origin defined in const.py.

Host strings live only in const.py. Callers ask this module for a URL at
request time so a later resolver can change the active origin in one place.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode, urlsplit

import aiohttp

from .const import (
    APIGEE_CLIENT_ID,
    PGE_API_BILL_PDF_PATH,
    PGE_API_GRAPHQL_PATH,
    PGE_API_HOST_ALLOW_FOREIGN_ENV,
    PGE_API_HOST_ENV,
    PGE_API_HOST_LABELS,
    PGE_API_HOST_SUFFIX,
    PGE_API_HOSTS,
    PGE_API_TOKEN_PATH,
)
from .exceptions import PGEConnectionError

_LOGGER = logging.getLogger(__name__)

# Credential-free probe budget. A live host answers in under half a second.
# A dead gateway is cut off here instead of waiting out its ~4.6s 503.
PROBE_TIMEOUT_SECONDS = 2.0
PROBE_IDP_TOKEN = "probe"
# Two authenticated attempts (sticky then fallback). Each attempt runs a full
# probe sweep (up to MAX_PROBES_PER_CYCLE probes at PROBE_TIMEOUT_SECONDS).
# One acquire() runs up to MAX_PROBES_PER_CYCLE probes (4 * 2.0s = 8s).
# Callers add exponential backoff between acquire() retries (MAX_AUTH_ATTEMPTS).
MAX_AUTH_ATTEMPTS = 2
MAX_PROBES_PER_CYCLE = 4
FAILURES_BEFORE_OPEN = 2
COOLDOWN_BASE_SECONDS = 30 * 60
COOLDOWN_CAP_SECONDS = 4 * 60 * 60
PREFERRED_RECHECK_SECONDS = 24 * 60 * 60


def preferred_origin() -> str:
    """Return the first configured Apigee origin."""
    return PGE_API_HOSTS[0]


def join_origin(origin: str, path: str) -> str:
    """Attach a path to an origin without duplicating slashes."""
    return origin.rstrip("/") + "/" + path.lstrip("/")


def graphql_url(origin: str | None = None) -> str:
    """GraphQL endpoint on the active origin, or on ``origin`` when given."""
    return join_origin(origin or active_origin(), PGE_API_GRAPHQL_PATH)


def bill_pdf_url(origin: str | None = None) -> str:
    """Bill PDF endpoint on the active origin, or on ``origin`` when given."""
    return join_origin(origin or active_origin(), PGE_API_BILL_PDF_PATH)


def token_exchange_url(origin: str | None = None) -> str:
    """Apigee token exchange URL. The client id is the public portal app id."""
    base = join_origin(origin or active_origin(), PGE_API_TOKEN_PATH)
    query = urlencode(
        {
            "client_id": APIGEE_CLIENT_ID,
            "response_type": "token",
            "redirect_uri": "",
        }
    )
    return f"{base}?{query}"


def public_hostname(url: str) -> str:
    """Hostname only, so logs and errors never include a query string."""
    return urlsplit(url).hostname or "unknown"


def _probe_detail(origin: str, statuses: dict[str, int | None]) -> str:
    """``host=status`` for the failure message; ``no-response`` on connect errors."""
    status = statuses.get(origin)
    return f"{public_hostname(origin)}={status if status is not None else 'no-response'}"


class HostOverrideError(ValueError):
    """Operator host string failed the domain check."""


def parse_host_override(raw: str | None, *, allow_foreign: bool = False) -> str | None:
    """Return ``https://host`` or None.

    Blank clears the override. The host must be HTTPS, have no userinfo,
    port, path, query, or fragment, and sit on the utility domain. A foreign
    host is accepted only when ``allow_foreign`` is set. That path is
    unsupported and stays off unless the operator opts in.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    parts = urlsplit(text)
    host = parts.hostname
    on_domain = bool(host and host.lower().endswith(PGE_API_HOST_SUFFIX))
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or not host
        or not (on_domain or allow_foreign)
    ):
        raise HostOverrideError("api_host_invalid")
    return f"https://{host.lower()}"


def resolve_operator_override(option: str | None) -> str | None:
    """Environment wins over the config option. Invalid values are ignored."""
    env = os.environ.get(PGE_API_HOST_ENV)
    allow_foreign = os.environ.get(PGE_API_HOST_ALLOW_FOREIGN_ENV) == "1"
    raw = env if isinstance(env, str) and env.strip() else option
    try:
        return parse_host_override(raw, allow_foreign=allow_foreign)
    except HostOverrideError:
        _LOGGER.warning("Ignoring invalid PGE API host override")
        return None


class FailureClass(StrEnum):
    """How a PGE API response should move the caller."""

    OK = "ok"
    HOST = "host"
    AUTH = "auth"
    FORBIDDEN = "forbidden"
    RATE_LIMIT = "rate_limit"
    APPLICATION = "application"


def _body_is_json(content_type: str | None, body: str | None) -> bool:
    if content_type and "json" in content_type.lower():
        return True
    if not body:
        return False
    stripped = body.lstrip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def classify_http(
    status: int,
    *,
    content_type: str | None = None,
    body: str | None = None,
) -> FailureClass:
    """Classify one PGE API response.

    Observed on 2026-10-09 with no account credentials:

    - A dead gateway returns HTTP 502, 503, or 504 with a text/plain body
      such as ``upstream connect error`` after several seconds. That is a
      host failure.
    - A live token route returns HTTP 401 with a text/plain body in well
      under a second when the probe header is not a Cognito token. HTTP 401
      is a credential failure even when the body is not JSON. It must not
      start a host sweep.
    - A live GraphQL route returns HTTP 400 with an application/json body.
      That is an application failure.
    - HTTP 403 stays on the current host. A WAF rejection is not a dead host.
    - HTTP 429 stays on the current host and uses the existing rate-limit path.
    - HTTP 501 on the credential-free probe is not a dead host. On an
      authenticated call, HTTP 501 with a non-JSON body is a host failure.
    - A connect error, DNS failure, or timeout is a host failure. Those have
      no status code, so callers pass them in separately and do not use this
      function.
    """
    if status == 401:
        return FailureClass.AUTH
    if status == 403:
        return FailureClass.FORBIDDEN
    if status == 429:
        return FailureClass.RATE_LIMIT
    if status in (502, 503, 504):
        return FailureClass.HOST
    if status < 400:
        return FailureClass.OK
    if _body_is_json(content_type, body):
        return FailureClass.APPLICATION
    return FailureClass.HOST


def host_detail(detail: str, url_or_host: str) -> str:
    """Append the hostname to an error string. Query strings stay out."""
    host = public_hostname(url_or_host) if "://" in url_or_host else url_or_host
    return f"{detail} (host {host})"


def probe_is_alive(
    status: int,
    *,
    content_type: str | None = None,
    body: str | None = None,
    strict: bool = False,
) -> bool:
    """Interpret the credential-free token probe.

    Listed hosts and an operator override use the loose check: HTTP 401 even
    when the body is text/plain, HTTP 400 with JSON, any 2xx, and HTTP 403,
    429, or 501. Dead: HTTP 502, 503, 504, or a non-JSON body on any other
    status.

    A guessed label uses ``strict``. Only HTTP 401 counts. A CDN or marketing
    site that answers 403 or 200 never receives a token. Timeouts are dead
    and never reach this function.
    """
    if strict:
        # Strict mode: only accept 401 with JSON body (real API), not text/plain (WAF page).
        if status != 401:
            return False
        return _body_is_json(content_type, body)
    if status in (502, 503, 504):
        return False
    if status in (401, 403, 429, 501) or status < 400:
        return True
    return _body_is_json(content_type, body)


def content_type_of(response: Any) -> str | None:
    """Read a content type without assuming the response has headers."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter("Content-Type")
    if isinstance(value, str):
        return value
    return None


@dataclass
class _HostHealth:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    cooldown_step: int = 0


@dataclass
class ApiHostResolver:
    """Pick a PGE API origin and remember which ones are sick.

    Credentials (Cognito ID token, Apigee bearer, account number) are sent
    only to a host that passed :meth:`probe`, or to an explicit operator
    override that already passed the utility-domain check. A password
    failure on the first candidate raises before any other host is tried.
    """

    origins: tuple[str, ...] = field(default_factory=lambda: PGE_API_HOSTS)
    now: Callable[[], float] = field(default=time.time)
    _health: dict[str, _HostHealth] = field(default_factory=dict)
    _verified: set[str] = field(default_factory=set)
    _sticky: str | None = None
    _last_known_good: str | None = None
    _override: str | None = None
    _announced: str | None = None
    _last_switch_at: float | None = None
    _last_switch_reason: str | None = None
    _last_preferred_check: float = 0.0
    _probe_status: dict[str, int | None] = field(default_factory=dict)

    @property
    def sticky(self) -> str | None:
        return self._sticky

    @property
    def last_switch_at(self) -> float | None:
        return self._last_switch_at

    @property
    def last_switch_reason(self) -> str | None:
        return self._last_switch_reason

    def set_override(self, origin: str | None) -> None:
        """Remember an operator origin. Logged once, hostname only.

        Clearing the pin drops that host from sticky and last-known-good so
        the next request returns to the preferred list instead of waiting
        for a failure or the 24 hour recheck.
        """
        if origin == self._override:
            return
        previous = self._override
        self._override = origin
        if origin:
            _LOGGER.info("PGE API host override: %s", public_hostname(origin))
            return
        if not previous:
            return
        self._verified.discard(previous)
        if self._sticky == previous:
            self._sticky = None
        if self._last_known_good == previous:
            self._last_known_good = None
        if self._announced == previous:
            self._announced = None
        _LOGGER.info("PGE API host override cleared: %s", public_hostname(previous))

    def mark_verified_for_tests(self, origin: str) -> None:
        """Treat ``origin`` as already probed. Production code does not call this."""
        self._verified.add(origin)
        self._sticky = origin
        self._last_known_good = origin
        self._announced = origin

    def in_cooldown(self, origin: str) -> bool:
        health = self._health.get(origin)
        return bool(health and health.cooldown_until > self.now())

    def is_trusted_origin(self, origin: str) -> bool:
        """Listed hosts and the operator pin may reject a real token as auth."""
        return origin in self.origins or origin == self._override

    def endpoint_origin(self) -> str:
        """This resolver's sticky host, else its pin, else its preferred host."""
        if self._sticky:
            return self._sticky
        if self._override:
            return self._override
        return self.origins[0]

    def mark_failure(self, origin: str, *, status: int | None) -> None:
        """Count a host-level failure and open the breaker on the second one."""
        del status
        self._verified.discard(origin)
        health = self._health.setdefault(origin, _HostHealth())
        health.consecutive_failures += 1
        if health.consecutive_failures >= FAILURES_BEFORE_OPEN:
            delay = min(COOLDOWN_CAP_SECONDS, COOLDOWN_BASE_SECONDS * (2**health.cooldown_step))
            health.cooldown_until = self.now() + delay
            health.cooldown_step += 1
            health.consecutive_failures = 0
        if self._sticky == origin:
            self._sticky = None

    def mark_success(self, origin: str, *, reason: str) -> None:
        self._health[origin] = _HostHealth()
        self._verified.add(origin)
        self._switch_to(origin, reason)

    def candidates(self) -> list[str]:
        """Sticky, then the preference list, then last-known-good. Cap the sweep."""
        ordered: list[str] = []

        def add(origin: str | None) -> None:
            if not origin or origin in ordered or self.in_cooldown(origin):
                return
            ordered.append(origin)

        if self._override:
            add(self._override)
        add(self._sticky)
        for origin in self.origins:
            add(origin)
        for origin in extra_candidate_origins(self.origins):
            add(origin)
        add(self._last_known_good)
        chosen = ordered[:MAX_PROBES_PER_CYCLE]
        chosen = self._keep_preferred_probe(chosen)
        _LOGGER.debug(
            "PGE API host candidates: %s",
            ", ".join(public_hostname(origin) for origin in chosen),
        )
        return chosen

    def _keep_preferred_probe(self, chosen: list[str]) -> list[str]:
        """Probe the preferred host once per cycle when cooldown would hide it.

        A guessed label can still be tried. The preferred host is added back
        when it is the only configured host cooling down, or when cooldown
        has removed every configured host.
        """
        if not self.origins:
            return chosen
        preferred = self.origins[0]
        if preferred in chosen or not self.in_cooldown(preferred):
            return chosen
        others_cooling = any(self.in_cooldown(origin) for origin in self.origins[1:])
        listed_ready = any(origin in chosen for origin in self.origins)
        if others_cooling and listed_ready:
            return chosen
        return [preferred, *chosen][:MAX_PROBES_PER_CYCLE]

    async def probe(self, session: aiohttp.ClientSession, origin: str) -> bool:
        """POST the token route with a fake id token. No account data is sent."""
        timeout = aiohttp.ClientTimeout(
            total=PROBE_TIMEOUT_SECONDS,
            connect=PROBE_TIMEOUT_SECONDS,
            sock_connect=PROBE_TIMEOUT_SECONDS,
        )
        status: int | None = None
        try:
            async with session.post(
                token_exchange_url(origin),
                headers={"idp_access_token": PROBE_IDP_TOKEN},
                timeout=timeout,
            ) as resp:
                status = resp.status
                raw = await resp.read()
                text = raw.decode("utf-8", errors="replace")[:300]
                strict = origin not in self.origins and origin != self._override
                alive = probe_is_alive(
                    resp.status,
                    content_type=content_type_of(resp),
                    body=text,
                    strict=strict,
                )
        except (TimeoutError, aiohttp.ClientError):
            alive = False
        self._probe_status[origin] = status
        _LOGGER.debug(
            "PGE API host probe host=%s status=%s alive=%s",
            public_hostname(origin),
            status if status is not None else "no-response",
            alive,
        )
        return alive

    async def acquire(self, session: aiohttp.ClientSession, *, exclude: set[str] | None = None) -> str:
        """Return a host that may receive credentials.

        See the class docstring. Worst case before this returns a failure is
        ``MAX_PROBES_PER_CYCLE`` probes at ``PROBE_TIMEOUT_SECONDS`` each.
        """
        await self._maybe_recheck_preferred(session)
        skipped = exclude or set()
        self._probe_status.clear()
        probed: list[str] = []
        for origin in self.candidates():
            if origin in skipped:
                continue
            if self._override and origin == self._override:
                if origin in self._verified and not self.in_cooldown(origin):
                    return origin
                if await self.probe(session, origin):
                    self.mark_success(origin, reason="operator override passed the credential-free probe")
                    return origin
                self.mark_failure(origin, status=None)
                probed.append(_probe_detail(origin, self._probe_status))
                continue
            if origin in self._verified and not self.in_cooldown(origin):
                return origin
            if await self.probe(session, origin):
                self.mark_success(origin, reason="credential-free probe succeeded")
                return origin
            self.mark_failure(origin, status=None)
            probed.append(_probe_detail(origin, self._probe_status))
        raise PGEConnectionError("PGE API host unavailable (probes: " + (", ".join(probed) or "none") + ")")

    async def _maybe_recheck_preferred(self, session: aiohttp.ClientSession) -> None:
        preferred = self.origins[0]
        if self._sticky in (None, preferred) or self.in_cooldown(preferred):
            return
        if self.now() - self._last_preferred_check < PREFERRED_RECHECK_SECONDS:
            return
        self._last_preferred_check = self.now()
        if await self.probe(session, preferred):
            self.mark_success(preferred, reason="higher-preference host passed the credential-free probe")

    def _switch_to(self, origin: str, reason: str) -> None:
        previous = self._announced
        self._sticky = origin
        self._last_known_good = origin
        if previous is None:
            self._announced = origin
            self._last_switch_at = self.now()
            self._last_switch_reason = reason
            return
        if previous == origin:
            return
        self._announced = origin
        self._last_switch_at = self.now()
        self._last_switch_reason = reason
        _LOGGER.info(
            "PGE API host changed: %s -> %s (%s)",
            public_hostname(previous),
            public_hostname(origin),
            reason,
        )

    def snapshot(self) -> dict[str, Any]:
        """Persist sticky host and cooldowns. No tokens."""
        return {
            "sticky": self._sticky,
            "last_known_good": self._last_known_good,
            "last_switch_at": self._last_switch_at,
            "last_switch_reason": self._last_switch_reason,
            "health": {
                origin: {
                    "consecutive_failures": health.consecutive_failures,
                    "cooldown_until": health.cooldown_until,
                    "cooldown_step": health.cooldown_step,
                }
                for origin, health in self._health.items()
            },
        }

    def restore(self, raw: dict[str, Any] | None) -> None:
        if not isinstance(raw, dict):
            return
        sticky = raw.get("sticky")
        if isinstance(sticky, str) and sticky in (*self.origins, self._override):
            self._sticky = sticky
            self._verified.add(sticky)
            self._announced = sticky
        last_good = raw.get("last_known_good")
        if isinstance(last_good, str):
            self._last_known_good = last_good
        switched = raw.get("last_switch_at")
        if isinstance(switched, (int, float)):
            self._last_switch_at = float(switched)
        reason = raw.get("last_switch_reason")
        if isinstance(reason, str):
            self._last_switch_reason = reason
        health = raw.get("health")
        if isinstance(health, dict):
            for origin, row in health.items():
                if not isinstance(origin, str) or not isinstance(row, dict):
                    continue
                self._health[origin] = _HostHealth(
                    consecutive_failures=int(row.get("consecutive_failures") or 0),
                    cooldown_until=float(row.get("cooldown_until") or 0),
                    cooldown_step=int(row.get("cooldown_step") or 0),
                )


def extra_candidate_origins(known: tuple[str, ...]) -> tuple[str, ...]:
    """Origins for labels that are not already in the preference list.

    The label and domain pieces live in const.py. This function only joins them.
    """
    known_hosts = {urlsplit(origin).hostname for origin in known}
    found: list[str] = []
    for label in PGE_API_HOST_LABELS:
        host = f"{label}{PGE_API_HOST_SUFFIX}"
        if host in known_hosts:
            continue
        found.append(f"https://{host}")
    return tuple(found)


def accept_discovered_host(hostname: str) -> str | None:
    """Return an origin only when the hostname is one bounded API label."""
    host = hostname.strip().lower().rstrip(".")
    label, separator, rest = host.partition(".")
    if separator != "." or f".{rest}" != PGE_API_HOST_SUFFIX:
        return None
    if label not in PGE_API_HOST_LABELS:
        return None
    return f"https://{host}"


_RESOLVER: ApiHostResolver | None = None
_ENTRY_RESOLVERS: dict[str, ApiHostResolver] = {}


def apply_configured_host(option: str | None, entry_id: str | None = None) -> ApiHostResolver:
    """Point one entry's resolver at the env or config-entry override.

    Each config entry keeps its own resolver. A blank option on one entry
    does not clear another entry's pin, and one entry's pin is not used for
    the other entry's credentials. Callers without an entry id still share
    the process resolver.
    """
    resolver = resolver_for_entry(entry_id) if entry_id else get_resolver()
    resolver.set_override(resolve_operator_override(option))
    return resolver


def resolver_for_entry(entry_id: str) -> ApiHostResolver:
    """Return the resolver owned by one config entry, creating it if needed."""
    resolver = _ENTRY_RESOLVERS.get(entry_id)
    if resolver is None:
        resolver = ApiHostResolver()
        _ENTRY_RESOLVERS[entry_id] = resolver
    return resolver


def forget_resolver(entry_id: str) -> None:
    """Drop an entry resolver on unload."""
    _ENTRY_RESOLVERS.pop(entry_id, None)


def resolver_from_client(client: Any) -> ApiHostResolver:
    """Use the client's resolver when it is a real one, else the process resolver."""
    resolver = getattr(client, "host_resolver", None)
    if isinstance(resolver, ApiHostResolver):
        return resolver
    return get_resolver()


def get_resolver() -> ApiHostResolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = ApiHostResolver()
    return _RESOLVER


def set_resolver(resolver: ApiHostResolver | None) -> None:
    global _RESOLVER
    _RESOLVER = resolver


def active_origin() -> str:
    return get_resolver().sticky or preferred_origin()
