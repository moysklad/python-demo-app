from __future__ import annotations

import logging
from dataclasses import dataclass

from app.logging_filters import SensitiveDataFilter


def test_sensitive_data_filter_redacts_sensitive_mappings_without_mutating_original():
    original_headers = {
        "Authorization": "Bearer token",
        "Accept-Encoding": "gzip",
        "Nested": {"Set-Cookie": "session=secret", "name": "ok"},
        "items": [{"x-api-key": "key-1", "label": "first"}],
    }
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "Request %s",
        (original_headers,),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.args["Authorization"] == "<redacted>"
    assert record.args["Nested"]["Set-Cookie"] == "<redacted>"
    assert record.args["items"][0]["x-api-key"] == "<redacted>"
    assert original_headers["Authorization"] == "Bearer token"
    assert original_headers["Nested"]["Set-Cookie"] == "session=secret"


def test_sensitive_data_filter_redacts_context_key_in_strings():
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "GET /entry/iframe?contextKey=de263ebd5e1dc05d96a97590eee5190d78a4aa05&appUid=python-demo-app.moysklad",
        (),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert "contextKey=<redacted>" in record.msg
    assert "appUid=python-demo-app.moysklad" in record.msg


def test_sensitive_data_filter_redacts_context_nonce_in_strings():
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "GET /utils/get-object?entity=customerorder&contextNonce=nonce-123&objectId=obj-1",
        (),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert "contextNonce=<redacted>" in record.msg
    assert "objectId=obj-1" in record.msg


def test_sensitive_data_filter_redacts_access_token_in_payload():
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "Request %s",
        ({"access_token": "token-123", "nested": {"access_token": "token-456"}},),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.args["access_token"] == "<redacted>"
    assert record.args["nested"]["access_token"] == "<redacted>"


def test_sensitive_data_filter_redacts_dataclass_with_sensitive_fields():
    @dataclass
    class Payload:
        access_token: str
        nested: dict[str, str]

    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "Request %s",
        (Payload(access_token="token-123", nested={"access_token": "token-456"}),),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.args[0]["access_token"] == "<redacted>"
    assert record.args[0]["nested"]["access_token"] == "<redacted>"


def test_sensitive_data_filter_redacts_access_token_in_json_string():
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        'HTTP request started\n\n{"access": [{"access_token": "token-123"}], "cause": "Install"}',
        (),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert '"access_token": "<redacted>"' in record.msg
    assert "token-123" not in record.msg
    assert '"cause": "Install"' in record.msg


def test_sensitive_data_filter_redacts_context_nonce_in_payload():
    record = logging.LogRecord(
        "app.http",
        logging.DEBUG,
        __file__,
        1,
        "Request %s",
        ({"contextNonce": "nonce-123", "nested": {"context_nonce": "nonce-456"}},),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.args["contextNonce"] == "<redacted>"
    assert record.args["nested"]["context_nonce"] == "<redacted>"
