"""Общие зависимости для эндпойнтов: разбор параметров и обработка ошибок."""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, Query

from app.pipeline.adjust import Adjustment, parse_route_factors


class ApiError(Exception):
    """Ошибка с кодом из контракта (раздел 40): {"code": ..., "message": ...}.

    Обработчик в main.py отдаёт её в этом формате. Поле detail дублирует
    message, чтобы фронт читал текст ошибки одинаково со старыми эндпойнтами.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def parse_date_param(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Параметр {name} должен быть датой в формате ГГГГ-ММ-ДД, "
                f"получено: {value!r}"
            ),
        ) from exc


def parse_routes_param(value: str | None) -> list | None:
    if not value:
        return None
    routes = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            routes.append(int(chunk))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Параметр routes — это номера маршрутов через запятую, "
                    f"например 17,25. Получено: {value!r}"
                ),
            ) from exc
    return routes or None


def adjustment_params(
    k_global: float = Query(
        1.0, ge=0.1, le=5.0,
        description="Общий множитель прогноза",
    ),
    k_weather: float = Query(
        1.0, ge=0.1, le=5.0,
        description="Поправка на погоду",
    ),
    weather_from: str | None = Query(None, description="Начало периода погоды"),
    weather_to: str | None = Query(None, description="Конец периода погоды"),
    k_event: float = Query(
        1.0, ge=0.1, le=5.0,
        description="Поправка на событие",
    ),
    event_from: str | None = Query(None, description="Начало события"),
    event_to: str | None = Query(None, description="Конец события"),
    k_routes: str | None = Query(
        None,
        description="Поправки по маршрутам, например 17:1.1,50:0.8",
    ),
) -> Adjustment:
    """Корректирующие коэффициенты из query-параметров.

    Используются интерфейсом: диспетчер двигает ползунок, фронт дёргает тот же
    эндпойнт с новым коэффициентом и сразу видит изменившийся прогноз.
    """
    return Adjustment(
        weather=k_weather,
        weather_from=parse_date_param(weather_from, "weather_from"),
        weather_to=parse_date_param(weather_to, "weather_to"),
        event=k_event,
        event_from=parse_date_param(event_from, "event_from"),
        event_to=parse_date_param(event_to, "event_to"),
        global_factor=k_global,
        route_factors=parse_route_factors(k_routes),
    )
