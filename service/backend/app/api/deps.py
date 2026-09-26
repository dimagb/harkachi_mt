"""Общие зависимости для эндпойнтов: разбор параметров и обработка ошибок."""

from __future__ import annotations

from datetime import date

from fastapi import Query

from app import config
from app.pipeline.adjust import Adjustment


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


K_RANGE = (0.1, 5.0)


def parse_date_param(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_DATE",
            f"Параметр {name} должен быть датой в формате ГГГГ-ММ-ДД, "
            f"получено: {value!r}",
        ) from exc


def check_route(route: int) -> int:
    if route not in config.ROUTES:
        raise ApiError(
            400, "INVALID_ROUTE",
            f"Маршрут {route} не поддерживается. Допустимые: "
            + ", ".join(str(r) for r in config.ROUTES),
        )
    return route


def parse_routes_param(value: str | None) -> list | None:
    """Опечатка в маршруте — ошибка, а не пустой ответ: на демо пустой
    график выглядел бы как исчезнувший прогноз."""
    if not value:
        return None
    routes = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            route = int(chunk)
        except ValueError as exc:
            raise ApiError(
                400, "INVALID_ROUTE",
                "Параметр routes — это номера маршрутов через запятую, "
                f"например 17,25. Получено: {value!r}",
            ) from exc
        routes.append(check_route(route))
    return routes or None


def check_hours(hour_from: int, hour_to: int) -> None:
    if hour_from > hour_to:
        raise ApiError(400, "INVALID_PARAMETER", "hour_from не может быть больше hour_to")


def check_period(dataset, source: str, start: date | None, end: date | None) -> list:
    """Период запроса против данных: вне горизонта — ошибка, частично вне —
    предупреждение в ответе. Молча отдавать пустоту нельзя."""
    if start and end and start > end:
        raise ApiError(400, "INVALID_PERIOD", f"date_from {start} позже date_to {end}")
    dates = dataset.forecast_dates if source == "forecast" else dataset.history_dates
    if not dates or (start is None and end is None):
        return []
    lo, hi = dates[0], dates[-1]
    kind = "прогноза" if source == "forecast" else "истории"
    if (end and end < lo) or (start and start > hi):
        raise ApiError(
            400, "OUT_OF_RANGE",
            f"Период {start or '…'} — {end or '…'} вне данных {kind}: есть {lo} — {hi}",
        )
    if (start and start < lo) or (end and end > hi):
        return [
            f"Запрошен период {start or '…'} — {end or '…'}, данные {kind} есть "
            f"только за {lo} — {hi}: ответ построен по пересечению"
        ]
    return []


def parse_route_factors_strict(raw: str | None) -> dict:
    """k_routes вида 17:1.1,50:0.8. Кривая запись — ошибка, а не молчаливый
    пропуск: иначе опечатка в поправке выглядела бы как её отсутствие."""
    if not raw:
        return {}
    result = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        route_part, sep, factor_part = chunk.partition(":")
        try:
            route, factor = int(route_part), float(factor_part)
        except ValueError as exc:
            raise ApiError(
                400, "INVALID_SCENARIO",
                f"k_routes — пары маршрут:коэффициент через запятую, например "
                f"17:1.1,50:0.8. Не разобрано: {chunk!r}",
            ) from exc
        check_route(route)
        _check_k("k_routes", factor)
        result[route] = factor
    return result


def _check_k(name: str, value: float) -> float:
    low, high = K_RANGE
    if not low <= value <= high:
        raise ApiError(
            400, "INVALID_SCENARIO",
            f"{name} — коэффициент от {low} до {high}, получено: {value}",
        )
    return value


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
    # Нечисловые значения и выход за 0.1–5.0 FastAPI отсекает раньше этой
    # функции; main.py переводит такие ошибки в 400 INVALID_SCENARIO.
    return Adjustment(
        weather=k_weather,
        weather_from=parse_date_param(weather_from, "weather_from"),
        weather_to=parse_date_param(weather_to, "weather_to"),
        event=k_event,
        event_from=parse_date_param(event_from, "event_from"),
        event_to=parse_date_param(event_to, "event_to"),
        global_factor=k_global,
        route_factors=parse_route_factors_strict(k_routes),
    )
