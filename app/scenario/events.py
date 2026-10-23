from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

# Действия, которые решение объявляет в блоке <scenario> дескриптора. name уходит в actionName
# запроса МоегоСклада, title видит администратор на странице настройки сценария.
SCENARIO_ACTIONS: dict[str, str] = {
    "log-event": "Записать событие в журнал решения",
    "fetch-object": "Запросить объект через JSON API",
    "reject": "Отклонить с сообщением пользователю",
}

# Сколько последних событий хранится на аккаунт: журнал в окне чатов показывает их целиком.
SCENARIO_EVENTS_LIMIT = 50

ScenarioOutcome = Literal["ok", "rejected", "failed"]


@dataclass
class ScenarioEvent:
    """Одно срабатывание действия сценария: что пришло от МоегоСклада и чем ответило решение."""

    app_id: str
    account_id: str
    action_name: str
    action_type: str
    object_type: str
    object_id: str
    outcome: ScenarioOutcome
    message: str = ""
    object_name: str = ""
    created_at: str = ""
    id: int | None = None


class ScenarioEventRepository(Protocol):
    def save(self, event: ScenarioEvent) -> None:
        ...

    def list_recent(self, app_id: str, account_id: str, limit: int = SCENARIO_EVENTS_LIMIT) -> list[ScenarioEvent]:
        ...


class ScenarioEventView(TypedDict):
    id: int | None
    createdAt: str
    actionName: str
    actionTitle: str
    actionType: str
    objectType: str
    objectId: str
    objectName: str
    outcome: ScenarioOutcome
    message: str


class ScenarioActionView(TypedDict):
    name: str
    title: str


def describe_scenario_event(event: ScenarioEvent) -> ScenarioEventView:
    return {
        "id": event.id,
        "createdAt": event.created_at,
        "actionName": event.action_name,
        "actionTitle": SCENARIO_ACTIONS.get(event.action_name, event.action_name),
        "actionType": event.action_type,
        "objectType": event.object_type,
        "objectId": event.object_id,
        "objectName": event.object_name,
        "outcome": event.outcome,
        "message": event.message,
    }


def describe_scenario_actions() -> list[ScenarioActionView]:
    return [{"name": name, "title": title} for name, title in SCENARIO_ACTIONS.items()]
