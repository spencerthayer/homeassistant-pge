"""API host constants, failure class, and failover."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
import pytest

from custom_components.pge_energy.api import PGEApiClient
from custom_components.pge_energy.api_host import (
    FAILURES_BEFORE_OPEN,
    PREFERRED_RECHECK_SECONDS,
    PROBE_IDP_TOKEN,
    ApiHostResolver,
    FailureClass,
    HostOverrideError,
    accept_discovered_host,
    apply_configured_host,
    bill_pdf_url,
    classify_http,
    extra_candidate_origins,
    forget_resolver,
    graphql_url,
    host_detail,
    parse_host_override,
    probe_is_alive,
    resolve_operator_override,
    token_exchange_url,
)
from custom_components.pge_energy.const import (
    APIGEE_CLIENT_ID,
    PGE_API_BILL_PDF_PATH,
    PGE_API_GRAPHQL_PATH,
    PGE_API_HOST_ENV,
    PGE_API_HOST_LABELS,
    PGE_API_HOSTS,
    PGE_API_TOKEN_PATH,
)
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGEAuthorizationError,
    PGEConnectionError,
    PGEGraphQLError,
    PGERateLimitError,
)
from custom_components.pge_energy.models import UsageResolution
from custom_components.pge_energy.portal_auth import _apigee_exchange_id_token
from custom_components.pge_energy.store import ImportStoreData

_COMPONENT_ROOT = Path(__file__).resolve().parents[3] / "custom_components"


def test_urls_attach_paths_to_the_preferred_origin() -> None:
    origin = PGE_API_HOSTS[0]
    assert graphql_url() == f"{origin}{PGE_API_GRAPHQL_PATH}"
    assert bill_pdf_url() == f"{origin}{PGE_API_BILL_PDF_PATH}"
    token = token_exchange_url()
    assert token.startswith(f"{origin}{PGE_API_TOKEN_PATH}?")
    assert f"client_id={APIGEE_CLIENT_ID}" in token
    assert "response_type=token" in token


def test_explicit_origin_overrides_the_preferred_host() -> None:
    origin = PGE_API_HOSTS[1]
    assert graphql_url(origin) == f"{origin}{PGE_API_GRAPHQL_PATH}"


def test_portlandgeneral_host_strings_live_only_in_const() -> None:
    hits: list[str] = []
    for path in _COMPONENT_ROOT.rglob("*"):
        if path.suffix not in {".py", ".js", ".json", ".md"}:
            continue
        if path.name == "const.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "portlandgeneral.com" in text:
            hits.append(str(path.relative_to(_COMPONENT_ROOT)))
    assert hits == []


def test_classify_http_matches_the_failure_taxonomy() -> None:
    assert classify_http(200, content_type="application/json", body="{}") is FailureClass.OK
    assert classify_http(503, content_type="text/plain", body="upstream connect error") is FailureClass.HOST
    assert classify_http(502, content_type="text/html", body="<html></html>") is FailureClass.HOST
    assert classify_http(504) is FailureClass.HOST
    assert classify_http(400, content_type="text/plain", body="upstream connect error") is FailureClass.HOST
    assert classify_http(401, content_type="text/plain", body="") is FailureClass.AUTH
    assert classify_http(401, content_type="application/json", body='{"message":"no"}') is FailureClass.AUTH
    assert classify_http(403, content_type="text/html", body="<html>blocked</html>") is FailureClass.FORBIDDEN
    assert classify_http(429, content_type="text/plain", body="slow down") is FailureClass.RATE_LIMIT
    assert (
        classify_http(400, content_type="application/json", body='{"errors":[{"message":"bad"}]}')
        is FailureClass.APPLICATION
    )
    assert classify_http(500, content_type="application/json", body='{"message":"no"}') is FailureClass.APPLICATION
    assert classify_http(501, content_type="text/plain", body="nope") is FailureClass.HOST


def test_host_detail_keeps_the_query_string_out_of_the_message() -> None:
    message = host_detail("Non-JSON auth response (HTTP 503)", token_exchange_url())
    assert "host api.portlandgeneral.com" in message
    assert "client_id" not in message
    assert "Bearer" not in message


class _Resp:
    def __init__(
        self,
        status: int,
        body: bytes = b"",
        content_type: str = "text/plain",
        payload: dict | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}
        self._payload = payload or {}

    async def read(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._body.decode()

    async def json(self, content_type: str | None = None) -> dict:
        del content_type
        return self._payload

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _Session:
    def __init__(self, handler) -> None:  # noqa: ANN001
        self.calls: list[tuple[str, dict]] = []
        self._handler = handler

    def post(self, url: str, **kwargs: object) -> _Resp:
        self.calls.append((url, kwargs))
        result = self._handler(url, kwargs)
        if isinstance(result, Exception):
            raise result
        return result


def test_probe_is_alive_matches_the_unauthenticated_checks() -> None:
    assert probe_is_alive(401, content_type="text/plain", body="") is True
    assert probe_is_alive(400, content_type="application/json", body='{"errors":[]}') is True
    assert probe_is_alive(403, content_type="text/html", body="<html>") is True
    assert probe_is_alive(501, content_type="text/plain", body="no") is True
    assert probe_is_alive(503, content_type="text/plain", body="upstream connect error") is False
    assert probe_is_alive(400, content_type="text/plain", body="upstream connect error") is False
    assert probe_is_alive(401, strict=True) is True
    assert probe_is_alive(403, content_type="text/html", body="<html>", strict=True) is False
    assert probe_is_alive(200, strict=True) is False
    assert probe_is_alive(501, strict=True) is False


@pytest.mark.asyncio
async def test_acquire_stops_at_the_first_live_probe() -> None:
    def handler(url: str, _kwargs: dict) -> _Resp:
        if url.startswith(PGE_API_HOSTS[0]):
            return _Resp(503, b"upstream connect error")
        return _Resp(401, b"")

    session = _Session(handler)
    resolver = ApiHostResolver()
    origin = await resolver.acquire(session)  # type: ignore[arg-type]
    assert origin == PGE_API_HOSTS[1]
    assert len(session.calls) == 2
    assert session.calls[0][1]["headers"]["idp_access_token"] == PROBE_IDP_TOKEN


def test_parse_host_override_accepts_a_utility_origin() -> None:
    assert parse_host_override("https://API.portlandgeneral.com/") == "https://api.portlandgeneral.com"
    assert parse_host_override("  ") is None
    assert parse_host_override(None) is None


@pytest.mark.parametrize(
    "raw",
    [
        "http://api.portlandgeneral.com",
        "https://user:secret@api.portlandgeneral.com",
        "https://api.portlandgeneral.com/pge-graphql",
        "https://api.portlandgeneral.com?client_id=secret",
        "https://evil.example",
        "https://api.portlandgeneral.com:8443",
    ],
)
def test_parse_host_override_rejects_unsafe_origins(raw: str) -> None:
    with pytest.raises(HostOverrideError):
        parse_host_override(raw)


def test_foreign_host_requires_the_unsupported_opt_in() -> None:
    raw = "https://gw.example"
    with pytest.raises(HostOverrideError):
        parse_host_override(raw)
    assert parse_host_override(raw, allow_foreign=True) == "https://gw.example"


def test_environment_override_wins_over_the_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PGE_API_HOST_ENV, "https://edge.portlandgeneral.com")
    assert resolve_operator_override("https://api.portlandgeneral.com") == "https://edge.portlandgeneral.com"


def test_invalid_environment_override_is_dropped_without_logging_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(PGE_API_HOST_ENV, "https://user:secret@evil.example/path?token=abc")
    with caplog.at_level(logging.WARNING, logger="custom_components.pge_energy.api_host"):
        assert resolve_operator_override("https://api.portlandgeneral.com") is None
    assert "secret" not in caplog.text
    assert "token=abc" not in caplog.text


@pytest.mark.asyncio
async def test_dead_override_is_probed_then_skipped(caplog: pytest.LogCaptureFixture) -> None:
    resolver = ApiHostResolver()
    override = "https://gw.portlandgeneral.com"

    def handler(url: str, _kwargs: dict) -> _Resp:
        if url.startswith(override):
            return _Resp(503, b"upstream connect error")
        return _Resp(401, b"")

    session = _Session(handler)
    with caplog.at_level(logging.INFO, logger="custom_components.pge_energy.api_host"):
        resolver.set_override(override)
        origin = await resolver.acquire(session)  # type: ignore[arg-type]
    assert origin == PGE_API_HOSTS[0]
    assert "PGE API host override: gw.portlandgeneral.com" in caplog.text
    before = len(caplog.records)
    resolver.set_override(override)
    assert len(caplog.records) == before


def test_api_host_snapshot_round_trips_without_tokens() -> None:
    resolver = ApiHostResolver(now=lambda: 1_000.0)
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])
    resolver.mark_failure(PGE_API_HOSTS[1], status=503)
    resolver.mark_failure(PGE_API_HOSTS[1], status=503)
    raw = resolver.snapshot()
    assert "Bearer" not in str(raw)
    loaded = ImportStoreData.from_dict(ImportStoreData(account_key="k", api_host=raw).to_dict())
    assert loaded.api_host is not None
    assert loaded.api_host["sticky"] == PGE_API_HOSTS[0]
    assert ImportStoreData.from_dict({"account_key": "k"}).api_host is None
    other = ApiHostResolver()
    other.restore({"sticky": "https://evil.example"})
    assert other.sticky is None


def test_label_candidates_skip_hosts_already_configured() -> None:
    extras = extra_candidate_origins(PGE_API_HOSTS)
    hosts = {item.removeprefix("https://").split(".", 1)[0] for item in extras}
    assert "api" not in hosts
    assert "apix" not in hosts
    assert hosts == set(PGE_API_HOST_LABELS) - {"api", "apix"}
    assert accept_discovered_host("Edge.portlandgeneral.com") == "https://edge.portlandgeneral.com"
    assert accept_discovered_host("evil.example") is None
    assert accept_discovered_host("api.evil.portlandgeneral.com") is None


@pytest.mark.asyncio
async def test_label_candidate_is_probed_before_it_can_take_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dead = set(PGE_API_HOSTS)

    def handler(url: str, kwargs: dict) -> _Resp:
        assert kwargs["headers"]["idp_access_token"] == PROBE_IDP_TOKEN
        assert "authorization" not in {key.lower() for key in kwargs["headers"]}
        if any(url.startswith(origin) for origin in dead):
            return _Resp(503, b"upstream connect error")
        return _Resp(401, b"")

    session = _Session(handler)
    resolver = ApiHostResolver()
    with caplog.at_level(logging.DEBUG, logger="custom_components.pge_energy.api_host"):
        origin = await resolver.acquire(session)  # type: ignore[arg-type]
    assert origin == "https://api-gw.portlandgeneral.com"
    assert len(session.calls) == 3
    assert "client_id" not in caplog.text
    assert "api-gw.portlandgeneral.com" in caplog.text


@pytest.mark.asyncio
async def test_guessed_host_403_never_receives_credentials() -> None:
    resolver = ApiHostResolver()
    for origin in PGE_API_HOSTS:
        resolver.mark_failure(origin, status=503)
        resolver.mark_failure(origin, status=503)

    def handler(url: str, kwargs: dict) -> _Resp:
        assert kwargs["headers"]["idp_access_token"] == PROBE_IDP_TOKEN
        assert "authorization" not in {key.lower() for key in kwargs["headers"]}
        if url.startswith("https://portal.portlandgeneral.com"):
            return _Resp(401, b"")
        if url.startswith(PGE_API_HOSTS[0]):
            return _Resp(503, b"upstream connect error")
        return _Resp(403, b"<html>", "text/html")

    session = _Session(handler)
    origin = await resolver.acquire(session)  # type: ignore[arg-type]
    assert origin == "https://portal.portlandgeneral.com"
    assert [url.split("/", 3)[2] for url, _kwargs in session.calls] == [
        "api.portlandgeneral.com",
        "api-gw.portlandgeneral.com",
        "gw.portlandgeneral.com",
        "portal.portlandgeneral.com",
    ]


def test_circuit_breaker_still_probes_a_cooled_preferred_host() -> None:
    resolver = ApiHostResolver(now=lambda: 1_000.0)
    host = PGE_API_HOSTS[0]
    other = PGE_API_HOSTS[1]
    for _ in range(FAILURES_BEFORE_OPEN):
        resolver.mark_failure(host, status=503)
    assert host in resolver.candidates()
    for _ in range(FAILURES_BEFORE_OPEN):
        resolver.mark_failure(other, status=503)
    chosen = resolver.candidates()
    assert host in chosen
    assert other not in chosen
    resolver.mark_success(host, reason="recovered")
    assert resolver.sticky == host


def test_clearing_the_override_leaves_the_old_pin() -> None:
    resolver = ApiHostResolver()
    pin = "https://gw.portlandgeneral.com"
    resolver.set_override(pin)
    resolver.mark_success(pin, reason="operator override passed the credential-free probe")
    resolver.set_override(None)
    assert resolver.sticky is None
    assert resolver.candidates()[0] == PGE_API_HOSTS[0]


def test_each_entry_keeps_its_own_override() -> None:
    try:
        first = apply_configured_host("https://apix.portlandgeneral.com", "entry-a")
        second = apply_configured_host(None, "entry-b")
        assert first is not second
        assert first.candidates()[0] == "https://apix.portlandgeneral.com"
        assert second.candidates()[0] == PGE_API_HOSTS[0]
    finally:
        forget_resolver("entry-a")
        forget_resolver("entry-b")


@pytest.mark.asyncio
async def test_return_to_preferred_when_the_higher_host_recovers(caplog: pytest.LogCaptureFixture) -> None:
    clock = {"now": 0.0}
    resolver = ApiHostResolver(now=lambda: clock["now"])
    resolver.mark_verified_for_tests(PGE_API_HOSTS[1])
    clock["now"] = PREFERRED_RECHECK_SECONDS
    session = _Session(lambda _url, _kwargs: _Resp(401, b""))
    with caplog.at_level(logging.INFO, logger="custom_components.pge_energy.api_host"):
        origin = await resolver.acquire(session)  # type: ignore[arg-type]
    assert origin == PGE_API_HOSTS[0]
    assert len(session.calls) == 1
    assert "PGE API host changed:" in caplog.text
    clock["now"] += 10
    session.calls.clear()
    again = await resolver.acquire(session)  # type: ignore[arg-type]
    assert again == PGE_API_HOSTS[0]
    assert session.calls == []


@pytest.mark.asyncio
async def test_listed_host_text_plain_401_stays_an_auth_error() -> None:
    resolver = ApiHostResolver()
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])
    session = _Session(lambda _url, _kwargs: _Resp(401, b"denied"))
    with pytest.raises(PGEAuthenticationError):
        await _apigee_exchange_id_token(session, "id-token", resolver)  # type: ignore[arg-type]
    assert len(session.calls) == 1
    assert session.calls[0][0].startswith(PGE_API_HOSTS[0])
    assert resolver.sticky == PGE_API_HOSTS[0]


@pytest.mark.asyncio
async def test_operator_pin_401_stays_an_auth_error() -> None:
    resolver = ApiHostResolver()
    pin = "https://gw.portlandgeneral.com"
    resolver.set_override(pin)
    resolver.mark_verified_for_tests(pin)

    def handler(url: str, kwargs: dict) -> _Resp:
        del url
        token = kwargs["headers"]["idp_access_token"]
        if token == PROBE_IDP_TOKEN:
            return _Resp(503, b"down")
        return _Resp(401, b"denied")

    session = _Session(handler)
    with pytest.raises(PGEAuthenticationError):
        await _apigee_exchange_id_token(session, "id-token", resolver)  # type: ignore[arg-type]
    credential_hosts = [
        url.split("/", 3)[2]
        for url, kwargs in session.calls
        if kwargs["headers"]["idp_access_token"] != PROBE_IDP_TOKEN
    ]
    assert credential_hosts == ["gw.portlandgeneral.com"]
    assert resolver.sticky == pin


@pytest.mark.asyncio
async def test_guessed_host_401_on_the_real_token_keeps_sweeping() -> None:
    resolver = ApiHostResolver()
    for origin in PGE_API_HOSTS:
        resolver.mark_failure(origin, status=503)
        resolver.mark_failure(origin, status=503)

    def handler(url: str, kwargs: dict) -> _Resp:
        host = url.split("/", 3)[2]
        token = (kwargs.get("headers") or {}).get("idp_access_token")
        if token == PROBE_IDP_TOKEN:
            if host in {"api-gw.portlandgeneral.com", "gw.portlandgeneral.com"}:
                return _Resp(401, b"")
            return _Resp(503, b"down")
        if host == "api-gw.portlandgeneral.com":
            return _Resp(401, b"denied")
        if host == "gw.portlandgeneral.com":
            return _Resp(200, b"{}", "application/json", {"access_token": "portal-token", "expires_at": 1})
        return _Resp(503, b"down")

    session = _Session(handler)
    token, _expires = await _apigee_exchange_id_token(session, "id-token", resolver)  # type: ignore[arg-type]
    assert token == "portal-token"
    assert resolver.sticky == "https://gw.portlandgeneral.com"
    credential_hosts = [
        url.split("/", 3)[2]
        for url, kwargs in session.calls
        if (kwargs.get("headers") or {}).get("idp_access_token") != PROBE_IDP_TOKEN
    ]
    assert credential_hosts == ["api-gw.portlandgeneral.com", "gw.portlandgeneral.com"]


@pytest.mark.asyncio
async def test_usage_401_does_not_probe_a_second_host() -> None:
    resolver = ApiHostResolver()
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])
    session = _Session(lambda _url, _kwargs: _Resp(401, b"no"))
    client = PGEApiClient(session, "secret-token", "enc", "acct", host_resolver=resolver)  # type: ignore[arg-type]
    with pytest.raises(PGEAuthenticationError):
        await client.get_usage(UsageResolution.HOURLY, datetime.now(UTC), datetime.now(UTC), "key")
    assert len(session.calls) == 1
    assert session.calls[0][0].startswith(PGE_API_HOSTS[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, PGEAuthorizationError),
        (429, PGERateLimitError),
    ],
)
async def test_auth_and_rate_limit_do_not_fail_over(status: int, expected: type[Exception]) -> None:
    resolver = ApiHostResolver()
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])
    session = _Session(lambda _url, _kwargs: _Resp(status, b"no"))
    client = PGEApiClient(session, "secret-token", "enc", "acct", host_resolver=resolver)  # type: ignore[arg-type]
    with pytest.raises(expected):
        await client.get_usage(UsageResolution.HOURLY, datetime.now(UTC), datetime.now(UTC), "key")
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_graphql_errors_stay_on_the_host_that_answered() -> None:
    resolver = ApiHostResolver()
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])
    payload = {"errors": [{"message": "Something unexpected happened"}]}
    session = _Session(lambda _url, _kwargs: _Resp(200, b"{}", "application/json", payload))
    client = PGEApiClient(session, "secret-token", "enc", "acct", host_resolver=resolver)  # type: ignore[arg-type]
    with pytest.raises(PGEGraphQLError):
        await client.get_usage(UsageResolution.HOURLY, datetime.now(UTC), datetime.now(UTC), "key")
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_usage_timeout_fails_over_once_and_hides_the_bearer(caplog: pytest.LogCaptureFixture) -> None:
    resolver = ApiHostResolver()
    resolver.mark_verified_for_tests(PGE_API_HOSTS[0])

    def handler(url: str, kwargs: dict) -> _Resp | Exception:
        headers = kwargs.get("headers") or {}
        if headers.get("idp_access_token") == PROBE_IDP_TOKEN:
            return _Resp(401, b"")
        del url
        return aiohttp.ClientConnectionError("down")

    session = _Session(handler)
    client = PGEApiClient(session, "secret-token", "enc", "acct", host_resolver=resolver)  # type: ignore[arg-type]
    with (
        caplog.at_level(logging.DEBUG, logger="custom_components.pge_energy.api_host"),
        pytest.raises(PGEConnectionError) as excinfo,
    ):
        await client.get_usage(UsageResolution.HOURLY, datetime.now(UTC), datetime.now(UTC), "key")
    assert "secret-token" not in str(excinfo.value)
    assert "secret-token" not in caplog.text
    assert "Bearer" not in caplog.text
    credential_calls = [url for url, kwargs in session.calls if "idp_access_token" not in (kwargs.get("headers") or {})]
    assert len(credential_calls) == 2
