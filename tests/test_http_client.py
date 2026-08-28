from __future__ import annotations

import logging
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
    retry_calls: list[None] = []

    with caplog.at_level(logging.INFO, logger="app.integrations.http_client"):
        result = client.request_json(
            "PUT",
            "https://example.test/status",
            "token",
            {"status": "Activated"},
            on_retry=lambda: retry_calls.append(None),
        )

    assert result == {"ok": True}
    assert [call["method"] for call in session.calls] == ["PUT", "PUT"]
    assert sleep_calls == [1.5]
    assert retry_calls == [None]
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
    retry_calls: list[None] = []

    result = client.request_json(
        "GET",
        "https://example.test/entity/store",
        "token",
        on_retry=lambda: retry_calls.append(None),
    )

    assert result is None
    assert retry_calls == [None, None]
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
