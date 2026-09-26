"""События сети: GET, POST, DELETE /api/network-events.

Контракт: docs/stas-mvp-architecture.md, разделы 17–21 и 26;
docs/frontend-tasks.md, задачи 9 и 10.

После каждого изменения сбрасывается кеш ответов. Без этого добавленное
закрытие не появилось бы в /api/forecast, пока старый ответ не вытеснится
из кеша, — на демо это выглядит как «добавили событие, ничего не изменилось».
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import config
from app.api.deps import ApiError
from app.pipeline import network_events as ne
from app.pipeline.cache import cache as response_cache

router = APIRouter(prefix="/network-events", tags=["события сети"])

TYPE_TITLES = {
    ne.FULL_CLOSURE: "Полное закрытие",
    ne.SHORTENING: "Укорочение маршрута",
    ne.MANUAL_MULTIPLIER: "Ручная поправка",
}
FACTOR_RANGE = (0.0, 5.0)


class NetworkEventIn(BaseModel):
    """Тело POST. Типы нарочно мягкие: форма шлёт пустую строку вместо null,
    а понятная ошибка 400 лучше, чем 422 от валидатора."""

    route: int | str
    type: str
    valid_from: str
    valid_to: str | None = None
    hour_from: int | str | None = None
    hour_to: int | str | None = None
    factor: float | str | None = None
    title: str | None = None
    source_url: str | None = None


def _invalid(message: str) -> ApiError:
    return ApiError(400, "INVALID_EVENT", message)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _date(value, name: str, required: bool) -> date | None:
    if _blank(value):
        if required:
            raise _invalid(f"Поле {name} обязательно, формат ГГГГ-ММ-ДД")
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise _invalid(
            f"Поле {name} должно быть датой ГГГГ-ММ-ДД, получено: {value!r}"
        ) from exc


def _hour(value, name: str) -> int | None:
    if _blank(value):
        return None
    try:
        hour = int(str(value).strip())
    except ValueError as exc:
        raise _invalid(f"Поле {name} — час от 0 до 23, получено: {value!r}") from exc
    if not 0 <= hour <= 23:
        raise _invalid(f"Поле {name} — час от 0 до 23, получено: {hour}")
    return hour


def _validate(body: NetworkEventIn) -> dict:
    try:
        route = int(str(body.route).strip())
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_ROUTE", f"Маршрут {body.route!r} не поддерживается"
        ) from exc
    if route not in config.ROUTES:
        raise ApiError(
            400, "INVALID_ROUTE",
            f"Маршрут {route} не поддерживается. Допустимые: {config.ROUTES}",
        )

    event_type = (body.type or "").strip().upper()
    if event_type not in ne.EVENT_TYPES:
        raise _invalid(
            f"Тип {body.type!r} не поддерживается. Допустимые: "
            + ", ".join(ne.EVENT_TYPES)
        )

    valid_from = _date(body.valid_from, "valid_from", required=True)
    valid_to = _date(body.valid_to, "valid_to", required=False)
    if valid_to is not None and valid_to < valid_from:
        raise _invalid("valid_to раньше valid_from")

    hour_from = _hour(body.hour_from, "hour_from")
    hour_to = _hour(body.hour_to, "hour_to")

    if event_type == ne.FULL_CLOSURE:
        # У закрытия множителя нет: прогноз просто 0.
        factor = None
    else:
        if _blank(body.factor):
            raise _invalid(f"Для {event_type} нужен коэффициент factor")
        try:
            factor = float(str(body.factor).strip().replace(",", "."))
        except ValueError as exc:
            raise _invalid(f"factor должен быть числом, получено: {body.factor!r}") from exc
        low, high = FACTOR_RANGE
        if not low <= factor <= high:
            raise _invalid(f"factor должен быть от {low} до {high}, получено: {factor}")

    title = (body.title or "").strip() or TYPE_TITLES[event_type]
    source_url = None if _blank(body.source_url) else body.source_url.strip()

    return {
        "route": route,
        "type": event_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "hour_from": hour_from,
        "hour_to": hour_to,
        "factor": factor,
        "title": title,
        "source_url": source_url,
    }


@router.get("", summary="Активные события сети")
def list_events(
    include_inactive: bool = Query(
        False, description="Показать и снятые события — для журнала"
    ),
) -> dict:
    repo = ne.get_repository()
    events = [e.as_dict() for e in repo.list(include_inactive=include_inactive)]
    return {"network_events": events, "total": len(events)}


@router.post("", status_code=201, summary="Добавить событие сети")
def create_event(body: NetworkEventIn) -> dict:
    fields = _validate(body)
    repo = ne.get_repository()

    candidate = ne.NetworkEvent(id=0, active=True, created_at="", **fields)
    duplicate = repo.find_duplicate(candidate)
    if duplicate is not None:
        raise ApiError(
            409, "DUPLICATE_EVENT",
            f"Такое событие уже активно: id {duplicate.id}, «{duplicate.title}»",
        )

    event = repo.add(fields)
    response_cache.invalidate()
    result = event.as_dict()
    if getattr(repo, "persist_error", None):
        result["warning"] = (
            "Событие действует, но не сохранено на диск и пропадёт "
            "после перезапуска сервиса"
        )
    return result


@router.delete("/{event_id}", summary="Снять событие сети")
def delete_event(event_id: int) -> dict:
    repo = ne.get_repository()
    event = repo.deactivate(event_id)
    if event is None:
        raise ApiError(404, "EVENT_NOT_FOUND", f"События с id {event_id} нет")
    response_cache.invalidate()
    return event.as_dict()
