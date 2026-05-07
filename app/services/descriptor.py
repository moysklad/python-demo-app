from __future__ import annotations

from app.config import AppConfig


def build_descriptor_xml(config: AppConfig) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ServerApplication xmlns="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xsi:schemaLocation="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2 https://apps-api.moysklad.ru/xml/ns/appstore/app/v2/application-v2.xsd">
    <iframe>
        <sourceUrl>{config.app_base_url}/entry/iframe</sourceUrl>
        <expand>true</expand>
    </iframe>
    <vendorApi>
        <endpointBase>{config.app_base_url}/vendor-endpoint</endpointBase>
    </vendorApi>
    <access>
        <resource>https://api.moysklad.ru/api/remap/1.2</resource>
        <scope>admin</scope>
    </access>
    <widgets>
        <document.customerorder.edit>
            <sourceUrl>{config.app_base_url}/entry/widget-customerorder</sourceUrl>
            <height>
                <fixed>525px</fixed>
            </height>
            <supports>
                <open-feedback/>
                <dirty-state/>
                <save-handler/>
                <update-provider/>
                <change-handler>
                    <validation-feedback/>
                </change-handler>
            </supports>
            <uses>
                <good-folder-selector/>
                <standard-dialogs/>
                <navigation-service/>
            </uses>
        </document.customerorder.edit>
        <document.invoiceout.edit>
            <sourceUrl>{config.app_base_url}/entry/widget-invoiceout</sourceUrl>
            <height>
                <fixed>525px</fixed>
            </height>
            <supports>
                <open-feedback/>
                <dirty-state/>
                <save-handler/>
                <update-provider/>
                <change-handler>
                    <validation-feedback/>
                </change-handler>
            </supports>
            <uses>
                <good-folder-selector/>
                <standard-dialogs/>
                <navigation-service/>
            </uses>
        </document.invoiceout.edit>
    </widgets>
    <popups>
        <popup>
            <name>some-popup</name>
            <sourceUrl>{config.app_base_url}/entry/popup</sourceUrl>
            <uses>
                <good-folder-selector/>
                <standard-dialogs/>
                <navigation-service/>
            </uses>
        </popup>
    </popups>
    <buttons>
        <button name="show-notification" title="Отобразить уведомление">
            <locations>
                <document.customerorder.edit/>
                <document.customerorder.list/>
            </locations>
        </button>
        <button name="navigate-to" title="Открыть ссылку">
            <locations>
                <document.customerorder.edit/>
            </locations>
        </button>
        <button name="show-popup" title="Открыть popup">
            <locations>
                <document.customerorder.edit/>
            </locations>
        </button>
    </buttons>
</ServerApplication>"""
