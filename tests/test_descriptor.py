from __future__ import annotations

from app.services.descriptor import build_descriptor_xml


def test_descriptor_contains_vendor_api_and_entries(app_config):
    descriptor = build_descriptor_xml(app_config)

    assert "<endpointBase>http://localhost:8080</endpointBase>" in descriptor
    assert "</vendorApi>\n    <loyaltyApi/>\n    <access>" in descriptor
    assert "<iframes>" in descriptor
    assert '<iframe type="main" sourceUrl="http://localhost:8080/entry/iframe-main" useContextKey="false">' in descriptor
    assert '<iframe type="mobile" sourceUrl="http://localhost:8080/entry/iframe-mobile"/>' in descriptor
    assert '<document.customerorder.edit useContextKey="false">' in descriptor
    assert '<document.invoiceout.edit useContextKey="false">' in descriptor
    assert '<iframe type="chat" sourceUrl="http://localhost:8080/entry/iframe-chat" useContextKey="false">' in descriptor
    assert descriptor.count("<user-context/>") == 4
    assert '<action name="log-event" title="Записать событие в журнал решения"/>' in descriptor
    assert '<action name="reject" title="Отклонить с сообщением пользователю"/>' in descriptor
    assert '<button name="show-popup" title="Открыть popup">' in descriptor
