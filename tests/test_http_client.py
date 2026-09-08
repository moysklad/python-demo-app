from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from typing import Any

import requests

from app.integrations.http_client import DEFAULT_HTTP_MAX_RETRIES, HttpClient, LognexRetry


class QueuedSession(requests.Session):
    def __init__(self, responses: list[requests.Response]) -> None:
        super().__init__()
        self._responses = responses
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.call_times: list[float] = []

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        with self._lock:
            self.calls.append({"method": method, "url": url, **kwargs})
            self.call_times.append(getattr(self, "_now", lambda: 0.0)())
            return self._responses.pop(0)


def _install_fake_clock(monkeypatch) -> tuple[list[float], list[float]]:
    now = [0.0]
    sleeps: list[float] = []

    monkeypatch.setattr("app.integrations.http_client.time.monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("app.integrations.http_client.time.sleep", fake_sleep)
    return sleeps, now


def make_response(status_code: int, *, headers: dict[str, str] | None = None, body: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = body.encode("utf-8")
    return response


def test_http_client_retries_lognex_429_after_vendor_retry_header(monkeypatch, caplog):
    # urllib3.Retry ждёт Retry-After в секундах; LognexRetry переводит X-Lognex-Retry-After из миллисекунд.
    sleep_calls, _now = _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "1500"}),
            make_response(200, body='{"ok": true}'),
        ]
    )
    client = HttpClient(session)

    with caplog.at_level(logging.INFO, logger="app.integrations.http_client"):
        result, retries = client.request_json_with_retries(
            "PUT",
            "https://example.test/status",
            "token",
            {"status": "Activated"},
        )

    assert result == {"ok": True}
    assert [call["method"] for call in session.calls] == ["PUT", "PUT"]
    assert sleep_calls == [1.5]
    assert retries == 1
    assert f"X-Lognex-Retry-After header delayMs=1500 retry=1/{DEFAULT_HTTP_MAX_RETRIES}" in caplog.text


def test_http_client_reports_all_retries_when_rate_limit_is_exhausted(monkeypatch):
    _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "100"})
            for _ in range(DEFAULT_HTTP_MAX_RETRIES + 1)
        ]
    )
    client = HttpClient(session)

    result, retries = client.request_json_with_retries(
        "GET",
        "https://example.test/entity/store",
        "token",
    )

    assert result is None
    assert retries == DEFAULT_HTTP_MAX_RETRIES
    assert len(session.calls) == DEFAULT_HTTP_MAX_RETRIES + 1


def test_http_client_keeps_urllib_default_retry_methods_for_lognex_429(monkeypatch):
    # POST не входит в стандартный allowlist urllib3.Retry, поэтому кастомный заголовок не делает его retryable.
    sleep_calls, _now = _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "1500"}),
            make_response(200, body='{"ok": true}'),
        ]
    )
    client = HttpClient(session)

    result = client.request_json("POST", "https://example.test/status", "token", {"status": "Activated"})

    assert result is None
    assert [call["method"] for call in session.calls] == ["POST"]
    assert sleep_calls == []


def test_http_client_paces_requests_by_advertised_rate_limit(monkeypatch):
    # 5 запросов за 3000 мс -> 600 мс между отправками. Первый ответ только учит spacing,
    # второй занимает слот, третий уже ждёт.
    sleeps, _now = _install_fake_clock(monkeypatch)
    limit_headers = {
        "X-RateLimit-Limit": "5",
        "X-RateLimit-Remaining": "4",
        "X-Lognex-Retry-TimeInterval": "3000",
    }
    session = QueuedSession(
        [
            make_response(200, headers=limit_headers, body='{"ok": true}'),
            make_response(200, headers=limit_headers, body='{"ok": true}'),
            make_response(200, headers=limit_headers, body='{"ok": true}'),
        ]
    )
    client = HttpClient(session)

    client.request_json("GET", "https://example.test/entity/store", "token")
    assert sleeps == []

    client.request_json("GET", "https://example.test/entity/store", "token")
    assert sleeps == []

    client.request_json("GET", "https://example.test/entity/store", "token")
    assert sleeps == [0.6]


def test_http_client_paces_each_account_separately(monkeypatch):
    # Лимиты в МойСкладе считаются по аккаунту, поэтому чужой аккаунт ждать не должен.
    sleeps, _now = _install_fake_clock(monkeypatch)
    limit_headers = {
        "X-RateLimit-Limit": "5",
        "X-Lognex-Retry-TimeInterval": "3000",
    }
    session = QueuedSession(
        [
            make_response(200, headers=limit_headers, body='{"ok": true}'),
            make_response(200, headers=limit_headers, body='{"ok": true}'),
        ]
    )
    client = HttpClient(session)

    client.request_json("GET", "https://example.test/entity/store", "token-first-account")
    client.request_json("GET", "https://example.test/entity/store", "token-second-account")

    assert sleeps == []


def test_http_client_does_not_add_response_rtt_to_reserved_spacing(monkeypatch):
    # observe() на 200 только запоминает spacing; слот уже занят в reserve() от момента отправки.
    sleeps, now = _install_fake_clock(monkeypatch)
    limit_headers = {
        "X-RateLimit-Limit": "5",
        "X-Lognex-Retry-TimeInterval": "3000",
    }
    session = QueuedSession(
        [
            make_response(200, headers=limit_headers, body='{"ok": true}'),
            make_response(200, headers=limit_headers, body='{"ok": true}'),
            make_response(200, headers=limit_headers, body='{"ok": true}'),
        ]
    )
    original_request = session.request

    def request_with_rtt(method: str, url: str, **kwargs: Any) -> requests.Response:
        response = original_request(method, url, **kwargs)
        now[0] += 0.2
        return response

    session.request = request_with_rtt
    client = HttpClient(session)

    client.request_json("GET", "https://example.test/entity/store", "token")
    client.request_json("GET", "https://example.test/entity/store", "token")
    assert sleeps == []

    client.request_json("GET", "https://example.test/entity/store", "token")
    assert sleeps == [0.4]


def test_lognex_retry_reads_vendor_header_as_milliseconds():
    retry = LognexRetry()
    response = make_response(429, headers={"X-Lognex-Retry-After": "1500"})

    assert retry.get_retry_after(response) == 1.5
    assert retry.is_retry("GET", 429, has_retry_after=True)
    assert not retry.is_retry("POST", 429, has_retry_after=True)


def test_http_client_uses_separate_session_for_each_thread(monkeypatch):
    created_sessions: list[requests.Session] = []
    session_factory = requests.Session

    def create_session() -> requests.Session:
        session = session_factory()
        created_sessions.append(session)
        return session

    monkeypatch.setattr("app.integrations.http_client.requests.Session", create_session)
    client = HttpClient()
    barrier = threading.Barrier(2)

    def get_session(_: int) -> requests.Session:
        session = client._session_for_current_thread()
        barrier.wait()
        return session

    with ThreadPoolExecutor(max_workers=2) as executor:
        sessions = list(executor.map(get_session, range(2)))

    assert sessions[0] is not sessions[1]
    assert len(created_sessions) == 2


def test_http_client_shares_retry_after_wait_across_threads(monkeypatch):
    sleeps, now = _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "1000"}),
            make_response(200, body='{"ok": true}'),
            make_response(200, body='{"ok": true}'),
        ]
    )
    session._now = lambda: now[0]
    client = HttpClient(session)

    def request_stores(_: int) -> tuple[Any | None, int]:
        return client.request_json_with_retries("GET", "https://example.test/entity/store", "token")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(request_stores, range(2)))

    assert all(result == {"ok": True} for result, _retries in results)
    assert len(session.calls) == 3
    assert session.call_times[0] == 0.0
    assert all(call_time >= 1.0 for call_time in session.call_times[1:])
    assert sleeps
    assert all(sleep == 1.0 for sleep in sleeps)
