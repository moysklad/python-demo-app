from __future__ import annotations

from typing import Any


def process_document_button_click(button_name: str, extension_point: str, object_id: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
    if button_name == "show-notification":
        role = user.get("role", "") if isinstance(user, dict) else ""
        return {
            "action": "showNotification",
            "params": {
                "text": f"Кнопка нажата в '{extension_point}' для объекта с ИД '{object_id}' пользователем с ролью {role}",
            },
        }

    if button_name == "navigate-to":
        return {
            "action": "navigateTo",
            "params": {
                "url": "https://api.whatsapp.com/send/?phone=%2B79127775533",
            },
        }

    if button_name == "show-popup":
        return {
            "action": "showPopup",
            "params": {
                "popupName": "some-popup",
                "popupParameters": {"paramStr": "Hello", "paramInt": 777},
            },
        }

    return {}


def process_list_button_click(button_name: str, extension_point: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
    if button_name != "show-notification":
        return {}

    items = ", ".join(f"'{item.get('id', '')}'" for item in objects)
    return {
        "action": "showNotification",
        "params": {
            "text": f"Кнопка нажата в '{extension_point}' для объектов {items}",
        },
    }
