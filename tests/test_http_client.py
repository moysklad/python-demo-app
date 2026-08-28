from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from typing import Any

import requests

from app.integrations.http_client import HttpClient


class QueuedSession(requests.Session):
    def __init__(self, responses: list[requests.Response]) -> None:
        super().__init__()
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0)


def make_response(status_code: int, *, headers: dict[str, str] | None = None, body: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = body.encode("utf-8")
    return response


def test_http_client_retries_lognex_429_after_vendor_retry_header(monkeypatch, caplog):
    # МойСклад возвращает задержку в миллисекундах, а urllib3 понимает только стандартный Retry-After.
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.integrations.http_client.time.sleep", sleep_calls.append)
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
    assert "X-Lognex-Retry-After header delayMs=1500 retry=1/2" in caplog.text


def test_http_client_reports_all_retries_when_rate_limit_is_exhausted(monkeypatch):
    monkeypatch.setattr("app.integrations.http_client.time.sleep", lambda _seconds: None)
    session = QueuedSession(
        [
            make_response(429, headers={"X-Lognex-Retry-After": "100"}),
            make_response(429, headers={"X-Lognex-Retry-After": "100"}),
            make_response(429, headers={"X-Lognex-Retry-After": "100"}),
        ]
    )
    client = HttpClient(session)

    result, retries = client.request_json_with_retries(
        "GET",
        "https://example.test/entity/store",
        "token",
    )

    assert result is None
    assert retries == 2
    assert len(session.calls) == 3


def test_http_client_keeps_urllib_default_retry_methods_for_lognex_429(monkeypatch):
    # POST не входит в стандартный allowlist urllib3.Retry, поэтому кастомный заголовок не делает его retryable.
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.integrations.http_client.time.sleep", sleep_calls.append)
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
