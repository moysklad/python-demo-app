from __future__ import annotations

from app.services.descriptor import build_descriptor_xml


def test_descriptor_contains_vendor_api_and_entries(app_config):
    descriptor = build_descriptor_xml(app_config)

    assert "<endpointBase>http://localhost:8080</endpointBase>" in descriptor
    assert "<sourceUrl>http://localhost:8080/entry/iframe</sourceUrl>" in descriptor
    assert "<document.customerorder.edit>" in descriptor
    assert '<button name="show-popup" title="Открыть popup">' in descriptor
