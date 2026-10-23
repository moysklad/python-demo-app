from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from typing import Any

import requests

from app.integrations.http_client import DEFAULT_HTTP_MAX_RETRIES, HttpClient


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


LIMIT_HEADERS = {"X-RateLimit-Limit": "5", "X-Lognex-Retry-TimeInterval": "3000"}


def test_http_client_retries_lognex_429_after_vendor_retry_header(monkeypatch, caplog):
    # X-Lognex-Retry-After приходит в миллисекундах; повтор считается и попадает в лог.
    sleep_calls, _now = _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "1500"}),
            make_response(200, body='{"ok": true}'),
        ]
    )
    client = HttpClient(session)

    with caplog.at_level(logging.INFO, logger="app.integrations.http_client"):
        result, retries = client.request_json_with_retries("PUT", "https://example.test/status", "token", {"status": "Activated"})

    assert result == {"ok": True}
    assert [call["method"] for call in session.calls] == ["PUT", "PUT"]
    assert sleep_calls == [1.5]
    assert retries == 1
    assert f"X-Lognex-Retry-After header delayMs=1500 retry=1/{DEFAULT_HTTP_MAX_RETRIES}" in caplog.text


def test_http_client_reports_all_retries_when_rate_limit_is_exhausted(monkeypatch):
    _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [make_response(429, headers={"X-Lognex-Retry-After": "100"}) for _ in range(DEFAULT_HTTP_MAX_RETRIES + 1)]
    )
    client = HttpClient(session)

    result, retries = client.request_json_with_retries("GET", "https://example.test/entity/store", "token")

    assert result is None
    assert retries == DEFAULT_HTTP_MAX_RETRIES
    assert len(session.calls) == DEFAULT_HTTP_MAX_RETRIES + 1


def test_http_client_does_not_retry_post_on_lognex_429(monkeypatch):
    # POST не входит в allowlist urllib3.Retry, поэтому кастомный заголовок не делает его retryable.
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


def test_http_client_paces_json_api_by_advertised_rate_limit(monkeypatch):
    # 5 запросов за 3000 мс -> 600 мс между отправками. Первый ответ только учит spacing,
    # второй занимает слот, третий уже ждёт. Лимит считается по аккаунту (токену), Vendor API не пейсится.
    sleeps, _now = _install_fake_clock(monkeypatch)
    session = QueuedSession([make_response(200, headers=LIMIT_HEADERS, body='{"ok": true}') for _ in range(6)])
    client = HttpClient(session)

    for _ in range(2):
        client.request_json("GET", "https://example.test/entity/store", "token", service_name="json-api")
    assert sleeps == []

    client.request_json("GET", "https://example.test/entity/store", "token", service_name="json-api")
    assert sleeps == [0.6]

    client.request_json("GET", "https://example.test/entity/store", "other-account-token", service_name="json-api")
    for _ in range(2):
        client.request_json("PUT", "https://example.test/apps/status", "vendor-token", service_name="vendor-api")
    assert sleeps == [0.6]


def test_http_client_shares_retry_after_wait_across_threads(monkeypatch):
    # Один 429 должен задержать все потоки с тем же токеном, а не только тот, который его получил.
    sleeps, now = _install_fake_clock(monkeypatch)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "1000"}),
            make_response(200, body='{"ok": true}'),
            make_response(200, body='{"ok": true}'),
            make_response(429, headers={"X-Lognex-Retry-After": "11000"}),
            make_response(200, body='{"ok": true}'),
        ]
    )
    session._now = lambda: now[0]
    client = HttpClient(session)

    def request_stores(_: int) -> tuple[Any | None, int]:
        return client.request_json_with_retries("GET", "https://example.test/entity/store", "token", service_name="json-api")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(request_stores, range(2)))

    assert all(result == {"ok": True} for result, _retries in results)
    assert len(session.calls) == 3
    assert session.call_times[0] == 0.0
    assert all(call_time >= 1.0 for call_time in session.call_times[1:])
    assert sleeps and all(sleep == 1.0 for sleep in sleeps)

    # Запрос с бюджетом не ждёт слот, который откроется позже дедлайна: он не отправляется вовсе.
    client.request_json("POST", "https://example.test/entity/demand", "token", {}, service_name="json-api")
    skipped = client.request_json_detailed("GET", "https://example.test/entity/store", "token", service_name="json-api", budget=5)
    assert skipped.status_code is None and len(session.calls) == 4
    served = client.request_json_detailed("GET", "https://example.test/entity/store", "token", service_name="json-api", budget=15)
    assert served.status_code == 200 and sleeps[-1] == 11.0 and session.calls[-1]["timeout"] == 4.0


def test_http_client_forgets_json_api_gate_after_ten_idle_minutes(monkeypatch):
    sleeps, now = _install_fake_clock(monkeypatch)
    limit_headers = {"X-RateLimit-Limit": "2", "X-Lognex-Retry-TimeInterval": "160"}
    session = QueuedSession(
        [
            make_response(200, headers=limit_headers, body="{}"),
            make_response(200, body="{}"),
            make_response(200, body="{}"),
        ]
    )
    client = HttpClient(session)

    client.request_json("GET", "https://example.test/entity/store", "idle-token", service_name="json-api")
    now[0] += 10 * 60 + 0.001
    client.request_json("GET", "https://example.test/entity/store", "idle-token", service_name="json-api")
    client.request_json("GET", "https://example.test/entity/store", "idle-token", service_name="json-api")

    assert sleeps == []
