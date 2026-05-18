from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util import Retry

DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_HTTP_MAX_RETRIES = 2
DEFAULT_HTTP_RETRY_BASE_SECONDS = 0.25
LOGNEX_RETRY_AFTER_HEADER = "X-Lognex-Retry-After"
MAX_LOGGED_RESPONSE_BODY_CHARS = 2000


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HttpResult:
    body: str
    attempt: int
    duration_ms: int


class HttpClient:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session or requests.Session()
        retry_adapter = HTTPAdapter(max_retries=_build_retries())
        self._session.mount("http://", retry_adapter)
        self._session.mount("https://", retry_adapter)

    def request_json(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
    ) -> Any | None:
        """Send an HTTP request and decode a JSON response body.

        Returns parsed JSON for successful responses with a non-empty body.
        Returns `None` for transport errors, non-2xx responses, empty bodies,
        or invalid JSON payloads.
        """
        result = self._request(method, url, bearer_token, data, service_name=service_name, retryable=retryable)

        if result is None or result.body == "":
            return None

        try:
            return json.loads(result.body)
        except ValueError as error:
            request_line = f"{method.upper()} {url}"
            logger.warning(
                "Failed to decode JSON for %s service=%s error=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                error,
                result.attempt,
                result.duration_ms,
            )
            return None

    def execute(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
    ) -> bool:
        """Send an HTTP request and return whether it completed successfully.

        This method is intended for command-style endpoints where response body
        content is irrelevant. It returns `True` for any successful 2xx
        response and `False` for transport errors or non-2xx responses.
        """
        return self._request(method, url, bearer_token, data, service_name=service_name, retryable=retryable) is not None

    def _request(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str,
        retryable: bool | None,
    ) -> _HttpResult | None:
        normalized_method = method.upper()
        request_line = f"{normalized_method} {url}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept-Encoding": "gzip",
        }

        _log_debug_request(request_line, service_name, headers, data)
        started_at = time.time()

        try:
            response = self._send_request(
                normalized_method,
                url,
                headers=headers,
                data=data,
                retryable=retryable,
            )
        except RequestException as error:
            duration_ms = int((time.time() - started_at) * 1000)
            logger.error(
                "Transport error %s service=%s error=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                error,
                1,
                duration_ms,
            )
            return None

        duration_ms = int((time.time() - started_at) * 1000)
        attempt = _response_attempt_count(response)
        body = response.text or ""
        _log_debug_response(request_line, service_name, response, attempt, duration_ms, body)

        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            logger.warning(
                "HTTP error %s service=%s status=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                response.status_code,
                attempt,
                duration_ms,
            )
            return None

        return _HttpResult(body=body, attempt=attempt, duration_ms=duration_ms)

    def _send_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: Any,
        retryable: bool | None,
    ) -> requests.Response:
        if retryable is False:
            request = requests.Request(method, url, headers=headers, json=data)
            prepared = self._session.prepare_request(request)
            adapter = HTTPAdapter(max_retries=False)
            return adapter.send(prepared, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)

        lognex_retry_count = 0
        while True:
            response = self._session.request(
                method,
                url,
                headers=headers,
                json=data,
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )

            retry_after_seconds = _lognex_retry_after_seconds(response)
            if (
                retry_after_seconds is None
                or lognex_retry_count >= DEFAULT_HTTP_MAX_RETRIES
                or not _is_lognex_rate_limit_retry(method, response)
            ):
                setattr(response, "_lognex_retry_count", lognex_retry_count)
                return response

            lognex_retry_count += 1
            time.sleep(retry_after_seconds)


def _build_retries() -> Retry:
    return Retry(
        total=DEFAULT_HTTP_MAX_RETRIES,
        backoff_factor=DEFAULT_HTTP_RETRY_BASE_SECONDS,
        raise_on_status=False,
        respect_retry_after_header=True,
    )


def _log_debug_request(request_line: str, service_name: str, headers: dict[str, str], data: Any) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    log_message = "Request %s service=%s\nheaders=%s"
    log_args: list[Any] = [request_line, service_name, headers]
    if data is not None:
        log_message += "\n\n%s"
        log_args.append(data)

    logger.debug(log_message, *log_args)


def _log_debug_response(
    request_line: str,
    service_name: str,
    response: requests.Response,
    attempt: int,
    duration_ms: int,
    body: str,
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    log_message = "Response %s service=%s status=%s attempt=%s durationMs=%s\nheaders=%s"
    log_args: list[Any] = [request_line, service_name, response.status_code, attempt, duration_ms, dict(response.headers)]
    if body != "":
        log_message += "\n\n%s"
        log_args.append(_sanitize_response_body_for_log(body))

    logger.debug(log_message, *log_args)


def _lognex_retry_after_seconds(response: requests.Response) -> float | None:
    retry_after_ms = response.headers.get(LOGNEX_RETRY_AFTER_HEADER)
    if retry_after_ms is None:
        return None

    try:
        retry_after_seconds = int(retry_after_ms) / 1000
    except ValueError:
        return None

    if retry_after_seconds < 0:
        return None

    return retry_after_seconds


def _is_lognex_rate_limit_retry(method: str, response: requests.Response) -> bool:
    return response.status_code == HTTPStatus.TOO_MANY_REQUESTS and method.upper() in Retry.DEFAULT_ALLOWED_METHODS


def _response_attempt_count(response: requests.Response) -> int:
    lognex_retry_count = getattr(response, "_lognex_retry_count", 0)
    retries = getattr(response.raw, "retries", None)
    history = getattr(retries, "history", None)
    if history is None:
        return lognex_retry_count + 1
    return lognex_retry_count + len(history) + 1


def _sanitize_response_body_for_log(body: str) -> str:
    if body == "":
        return ""
    try:
        serialized = json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:
        serialized = body
    if len(serialized) <= MAX_LOGGED_RESPONSE_BODY_CHARS:
        return serialized
    return f"{serialized[:MAX_LOGGED_RESPONSE_BODY_CHARS]}... [truncated {len(serialized) - MAX_LOGGED_RESPONSE_BODY_CHARS} chars]"
