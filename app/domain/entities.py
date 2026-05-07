from __future__ import annotations


ENTITIES_MAP = {
    "customerorder": "Заказ покупателя",
    "invoiceout": "Счет покупателю",
}


def is_supported_entity(entity: str) -> bool:
    return entity in ENTITIES_MAP
