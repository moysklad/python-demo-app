from __future__ import annotations

import json
import logging
import time
from http import HTTPStatus
from dataclasses import dataclass
from typing import Any

import urllib3
from urllib3.exceptions import HTTPError
from urllib3.util import Retry

DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_HTTP_MAX_RETRIES = 2
DEFAULT_HTTP_RETRY_BASE_SECONDS = 0.25
MAX_LOGGED_RESPONSE_BODY_CHARS = 2000


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HttpResult:
    body: str
    attempt: int
    duration_ms: int


class HttpClient:
    def __init__(self, pool_manager: Any | None = None) -> None:
        self._pool_manager = pool_manager or urllib3.PoolManager()

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
        retries = _build_retries(retryable)
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept-Encoding": "gzip",
        }
        request_body = None

        if data is not None:
            headers["Content-Type"] = "application/json"
            request_body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        if logger.isEnabledFor(logging.DEBUG):
            log_message = "Request %s service=%s\nheaders=%s"
            log_args = [request_line, service_name, headers]
            if data is not None:
                log_message += "\n\n%s"
                log_args.append(data)

            logger.debug(log_message, *log_args)
        started_at = time.time()

        try:
            response = self._pool_manager.request(
                normalized_method,
                url,
                body=request_body,
                headers=headers,
                timeout=urllib3.Timeout(total=DEFAULT_HTTP_TIMEOUT_SECONDS),
                retries=retries,
                redirect=True,
                preload_content=True,
                decode_content=True,
            )
        except HTTPError as error:
            duration_ms = int((time.time() - started_at) * 1000)
            logger.error(
                "Transport error %s service=%s error=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                error,
                _retry_attempt_count(retries),
                duration_ms,
            )
            return None

        duration_ms = int((time.time() - started_at) * 1000)
        attempt = _response_attempt_count(response)
        body = _decode_response_body(response.data)

        if logger.isEnabledFor(logging.DEBUG):
            log_message = "Response %s service=%s status=%s attempt=%s durationMs=%s\nheaders=%s"
            log_args = [request_line, service_name, response.status, attempt, duration_ms, getattr(response, "headers", None)]
            if body != "":
                log_message += "\n\n%s"
                log_args.append(_sanitize_response_body_for_log(body))

            logger.debug(log_message, *log_args)

        if not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
            logger.warning(
                "HTTP error %s service=%s status=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                response.status,
                attempt,
                duration_ms,
            )
            return None

        return _HttpResult(body=body, attempt=attempt, duration_ms=duration_ms)


def _build_retries(retryable: bool | None) -> Retry | bool:
    if retryable is False:
        return False

    return Retry(
        total=DEFAULT_HTTP_MAX_RETRIES,
        backoff_factor=DEFAULT_HTTP_RETRY_BASE_SECONDS,
        raise_on_status=False,
        respect_retry_after_header=True,
    )


def _decode_response_body(body: bytes | str | None) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    return body.decode("utf-8")


def _response_attempt_count(response: Any) -> int:
    retries = getattr(response, "retries", None)
    history = getattr(retries, "history", None)
    if history is None:
        return 1
    return len(history) + 1


def _retry_attempt_count(retries: Retry | bool) -> int:
    if not isinstance(retries, Retry):
        return 1
    return retries.total + 1


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
