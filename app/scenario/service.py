from __future__ import annotations

import logging
from typing import Any

from app.config import AppConfig
from app.domain.app_instance import AppInstance, AppInstanceRepository
from app.integrations.json_api import JsonApiFactory, json_api_entity
from app.scenario.events import (
    SCENARIO_ACTIONS,
    ScenarioEvent,
    ScenarioEventRepository,
    describe_scenario_actions,
    describe_scenario_event,
)
from app.services.common import ServiceResponse

logger = logging.getLogger(__name__)

# Код ошибки произвольный: МойСклад показывает пользователю errorMessage, code нужен только для своих логов.
REJECT_ERROR_CODE = 1001


class ScenarioService:
    """
    Обработчик действий из сценариев МоегоСклада: POST .../apps/{appId}/{accountId}/scenario.
    Каждое срабатывание пишется в журнал, который показывает окно чатов решения.
    """

    def __init__(self, config: AppConfig, app_repository: AppInstanceRepository, repository: ScenarioEventRepository, json_api_factory: JsonApiFactory) -> None:
        self._config = config
        self._app_repository = app_repository
        self._repository = repository
        self._json_api_factory = json_api_factory

    def handle(self, app_id: str, account_id: str, body: dict[str, Any]) -> ServiceResponse:
        """
        Ответ формируется по правилам Vendor API: 200 — действие обработано, 400 с объектом error —
        отказ по вине пользователя (сообщение попадет в историю сценария), 5xx — МойСклад повторит запрос.
        Ответить нужно быстрее 10 секунд, иначе МойСклад считает попытку неуспешной и тоже повторяет.
        """
        action_name = _string(body.get("actionName"))
        action_type = _string(body.get("actionType"))
        object_id = _string(body.get("objectId"))
        object_type = _string(body.get("objectType"))
        if not action_name or not action_type or not object_id or not object_type:
            return _error_response("В запросе нет actionName, actionType, objectId или objectType")

        if action_name not in SCENARIO_ACTIONS:
            logger.warning("Unknown scenario action %s for appId=%s on accountId=%s", action_name, app_id, account_id)
            return _error_response(f"Решение не поддерживает действие «{action_name}»")

        event = ScenarioEvent(
            app_id=app_id,
            account_id=account_id,
            action_name=action_name,
            action_type=action_type,
            object_type=object_type,
            object_id=object_id,
            outcome="ok",
        )

        if action_name == "reject":
            event.outcome = "rejected"
            event.message = f"Решение отклонило действие для объекта {object_type} {object_id}"
            self._save(event)
            return _error_response(event.message, REJECT_ERROR_CODE)

        if action_name == "fetch-object":
            app = self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)
            response = self._json_api_factory.create(app.access_token).get_scenario_object(json_api_entity(object_type), object_id)
            obj = response.json_body if isinstance(response.json_body, dict) else {}
            if not response.successful or not obj.get("name"):
                event.outcome = "failed"
                if response.status_code is not None and 400 <= response.status_code < 500 and response.status_code != 429:
                    event.message = f"JSON API не отдал объект {object_type} {object_id}: статус {response.status_code}, повтор не поможет"
                    self._save(event)
                    return _error_response(event.message)
                event.message = "Не удалось получить объект через JSON API, МойСклад повторит действие"
                self._save(event)
                return ServiceResponse(status_code=502)

            event.object_name = str(obj["name"])
            event.message = f"Получен объект {object_type} «{event.object_name}»"
            self._save(event)
            return ServiceResponse(status_code=200)

        event.message = f"Событие {action_type} для объекта {object_type} {object_id} записано"
        self._save(event)
        return ServiceResponse(status_code=200)

    def journal(self, account_id: str) -> dict[str, Any]:
        """Журнал событий и список действий из дескриптора для окна чатов."""
        events = self._repository.list_recent(self._config.app_id, account_id)
        return {
            "scenarioActions": describe_scenario_actions(),
            "scenarioEvents": [describe_scenario_event(event) for event in events],
        }

    def _save(self, event: ScenarioEvent) -> None:
        self._repository.save(event)
        logger.info(
            "Scenario action %s (%s) for %s %s on accountId=%s: %s",
            event.action_name,
            event.action_type,
            event.object_type,
            event.object_id,
            event.account_id,
            event.outcome,
        )


def _error_response(message: str, code: int | None = None) -> ServiceResponse:
    error: dict[str, Any] = {"errorMessage": message}
    if code is not None:
        error["code"] = code
    return ServiceResponse(status_code=400, json_body={"error": error})


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
