from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol, TypedDict


@dataclass
class LoyaltyInstallation:
    """
    Подключение программы лояльности на аккаунте. Настройки меняются в два шага: сначала решение
    запоминает ожидающий токен, потом передает его в МойСклад. Пока исход не подтвержден, провайдер
    принимает и действующий, и ожидающий токен — так неудачное переподключение не ломает кассу.
    """

    app_id: str
    account_id: str
    # Токен, который МойСклад принял через Vendor API. None — подключения еще не было.
    provider_token: str | None = None
    external_search: bool = False
    # Момент, когда Vendor API принял настройки. None означает, что МойСклад о подключении не знает.
    connected_at: str | None = None
    # Настройки, отправленные в МойСклад, но еще не подтвержденные.
    pending_provider_token: str | None = None
    pending_external_search: bool = False

    def is_connected(self) -> bool:
        return self.connected_at is not None

    def accepts_token(self, token: str) -> bool:
        return any(
            candidate is not None and hmac.compare_digest(candidate.encode(), token.encode())
            for candidate in (self.provider_token, self.pending_provider_token)
        )

    def allows_external_search(self) -> bool:
        return self.external_search or (self.pending_provider_token is not None and self.pending_external_search)

    def begin_update(self, provider_token: str | None, external_search: bool) -> None:
        self.pending_provider_token = provider_token or self.provider_token or secrets.token_hex(32)
        self.pending_external_search = external_search

    def confirm_update(self) -> None:
        self.provider_token = self.pending_provider_token
        self.external_search = self.pending_external_search
        self.connected_at = datetime.now(timezone.utc).isoformat()
        self.discard_update()

    def discard_update(self) -> None:
        self.pending_provider_token = None
        self.pending_external_search = False

    def mark_disconnected(self) -> None:
        """
        МойСклад удаляет настройки лояльности вместе с решением, поэтому после повторной установки
        их нужно передать заново. Токен при этом сохраняется.
        """
        self.connected_at = None
        self.discard_update()


class LoyaltyInstallationRepository(Protocol):
    def load(self, app_id: str, account_id: str) -> LoyaltyInstallation | None:
        ...

    def find_by_token(self, token: str) -> LoyaltyInstallation | None:
        ...

    def save(self, installation: LoyaltyInstallation) -> None:
        ...


class LoyaltyConnectionState(TypedDict):
    state: Literal["not-connected", "connected", "reconnect-required"]
    badge: Literal["green", "orange"]
    title: str
    details: str
    externalSearch: bool


def describe_loyalty_connection(installation: LoyaltyInstallation | None) -> LoyaltyConnectionState:
    """
    Состояние подключения для вкладки «Программа лояльности».
    Подключение опционально: на статус решения (SettingsRequired/Activated) оно не влияет.
    """
    if installation is None or installation.provider_token is None:
        return {
            "state": "not-connected",
            "badge": "orange",
            "title": "Программа лояльности не подключена",
            "details": "Передайте адрес и токен вашего Loyalty API через Vendor API, чтобы МойСклад начал обращаться к программе лояльности.",
            "externalSearch": False,
        }

    if not installation.is_connected():
        return {
            "state": "reconnect-required",
            "badge": "orange",
            "title": "Требуется повторное подключение",
            "details": "Решение переустанавливали: МойСклад удалил настройки лояльности вместе с решением. Токен сохранен, отправьте настройки заново.",
            "externalSearch": installation.external_search,
        }

    return {
        "state": "connected",
        "badge": "green",
        "title": "Программа лояльности подключена",
        "details": (
            "Внешний поиск покупателей включен: МойСклад ищет покупателей через ваш Loyalty API."
            if installation.external_search
            else "Внешний поиск покупателей выключен: МойСклад ищет покупателей в своей базе."
        ),
        "externalSearch": installation.external_search,
    }
