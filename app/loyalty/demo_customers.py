from __future__ import annotations

from typing import Any

# Демонстрационная база покупателей для внешнего поиска.
# ВНИМАНИЕ! Поля id и msId МойСклад разбирает как UUID, произвольные строки не пройдут.
# msId заполняется только для покупателей, которые уже заведены в МоемСкладе.
LOYALTY_DEMO_CUSTOMERS: tuple[dict[str, Any], ...] = (
    {
        "id": "7c3b1a52-2f4d-4f0a-9a6c-2c9f5f0b1d11",
        "name": "Иванов Иван",
        "discountCardNumber": "1000000000001",
        "phone": "+79000000001",
        "email": "ivanov@example.com",
        "legalFirstName": "Иван",
        "legalLastName": "Иванов",
        "sex": "MALE",
    },
    {
        "id": "8d4c2b63-3a5e-4b1b-8b7d-3daf6a1c2e22",
        "name": "Петрова Мария",
        "discountCardNumber": "1000000000002",
        "phone": "+79000000002",
        "email": "petrova@example.com",
        "legalFirstName": "Мария",
        "legalLastName": "Петрова",
        "sex": "FEMALE",
    },
    {
        "id": "9e5d3c74-4b6f-4c2c-9c8e-4ebf7b2d3f33",
        "name": "Сидоров Петр",
        "discountCardNumber": "1000000000003",
        "phone": "+79000000003",
        "email": "sidorov@example.com",
        "legalFirstName": "Петр",
        "legalLastName": "Сидоров",
        "sex": "MALE",
    },
)

SEARCH_FIELDS = ("name", "discountCardNumber", "phone", "email")


def find_loyalty_demo_customers(search: str) -> list[dict[str, Any]]:
    """Поиск по подстроке в имени, номере карты, телефоне или email; пустая строка возвращает всех."""
    query = search.strip().lower()
    if query == "":
        return list(LOYALTY_DEMO_CUSTOMERS)

    return [customer for customer in LOYALTY_DEMO_CUSTOMERS if any(query in customer[field].lower() for field in SEARCH_FIELDS)]
