"""Эндпойнты прогноза: выборка по маршруту, остановке, интервалу и горизонту."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    ApiError,
    adjustment_params,
    check_hours,
    check_period,
    check_route,
    parse_date_param,
    parse_routes_param,
)
from app.pipeline import aggregate
from app.pipeline.adjust import Adjustment
from app.pipeline.ingest import get_dataset
from app.pipeline.network_events import get_repository as network_repository

router = APIRouter(prefix="/forecast", tags=["прогноз"])

HORIZON_TO_GRANULARITY = {
    "day": "hour",      # краткосрочный: сутки по часам
    "month": "day",     # среднесрочный: месяц по дням
    "year": "month",    # долгосрочный: год по месяцам
}


@router.get("", summary="Прогноз с фильтрами и агрегацией")
def get_forecast(
    routes: str | None = Query(None, description="Маршруты через запятую, напр. 17,25"),
    date_from: str | None = Query(None, description="Начало периода, ГГГГ-ММ-ДД"),
    date_to: str | None = Query(None, description="Конец периода, ГГГГ-ММ-ДД"),
    hour_from: int = Query(0, ge=0, le=23, description="Начальный час"),
    hour_to: int = Query(23, ge=0, le=23, description="Конечный час"),
    horizon: str = Query(
        "day",
        description="Горизонт: day (сутки по часам), month (месяц по дням), "
                    "year (год по месяцам)",
    ),
    granularity: str | None = Query(
        None, description="Переопределить шаг: hour, day или month"
    ),
    split_by_route: bool = Query(False, description="Разбить ряд по маршрутам"),
    source: str = Query("forecast", description="forecast или history"),
    adjustment: Adjustment = Depends(adjustment_params),
) -> dict:
    if horizon not in HORIZON_TO_GRANULARITY:
        raise ApiError(
            400, "INVALID_PARAMETER",
            f"horizon принимает значения day, month или year. Получено: {horizon!r}",
        )
    if granularity is not None and granularity not in aggregate.GRANULARITIES:
        raise ApiError(
            400, "INVALID_PARAMETER",
            f"granularity принимает значения hour, day или month. Получено: {granularity!r}",
        )
    check_hours(hour_from, hour_to)
    if source not in ("forecast", "history"):
        raise ApiError(
            400, "INVALID_PARAMETER", "source принимает значения forecast или history"
        )

    step = granularity or HORIZON_TO_GRANULARITY[horizon]
    dataset = get_dataset()
    if source == "forecast" and not dataset.forecast:
        raise ApiError(503, "FORECAST_NOT_LOADED", "Прогноз не загружен: нет файла submission.csv")
    start = parse_date_param(date_from, "date_from")
    end = parse_date_param(date_to, "date_to")
    route_list = parse_routes_param(routes)
    warnings = check_period(dataset, source, start, end)
    result = aggregate.series(
        dataset,
        routes=route_list,
        date_from=start,
        date_to=end,
        hour_from=hour_from,
        hour_to=hour_to,
        granularity=step,
        source=source,
        adjustment=adjustment,
        split_by_route=split_by_route,
        network=network_repository().effect(),
    )
    result["horizon"] = horizon
    if warnings:
        result["warnings"] = warnings
    return result


@router.get("/routes", summary="Сводка по маршрутам за период")
def forecast_by_routes(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    adjustment: Adjustment = Depends(adjustment_params),
) -> dict:
    dataset = get_dataset()
    network = network_repository().effect()
    start = parse_date_param(date_from, "date_from")
    end = parse_date_param(date_to, "date_to")
    warnings = check_period(dataset, "forecast", start, end)
    result = {
        "period": {"from": date_from, "to": date_to},
        "routes": aggregate.route_totals(
            dataset,
            date_from=start,
            date_to=end,
            adjustment=adjustment,
            network=network,
        ),
        "adjustments": adjustment.describe(),
        "network_events": network.relevant(None, start, end),
    }
    secondary = network.secondary_effects(None, start, end)
    if secondary:
        result["secondary_effects"] = secondary
    if warnings:
        result["warnings"] = warnings
    return result


@router.get("/stops", summary="Разложение прогноза по остановкам (оценочное)")
def forecast_by_stops(
    route: int = Query(..., description="Номер маршрута"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    adjustment: Adjustment = Depends(adjustment_params),
) -> dict:
    check_route(route)
    check_hours(hour_from, hour_to)
    dataset = get_dataset()
    network = network_repository().effect()
    start = parse_date_param(date_from, "date_from")
    end = parse_date_param(date_to, "date_to")
    warnings = check_period(dataset, "forecast", start, end)
    result = aggregate.by_stop(
        dataset,
        route,
        date_from=start,
        date_to=end,
        hour_from=hour_from,
        hour_to=hour_to,
        adjustment=adjustment,
        network=network,
    )
    result["network_events"] = network.relevant([route], start, end)
    secondary = network.secondary_effects([route], start, end)
    if secondary:
        result["secondary_effects"] = secondary
    if warnings:
        result["warnings"] = warnings
    if not result["stops"]:
        result["note"] = (
            f"Для маршрута {route} в справочниках нет координат остановок. "
            "Прогноз доступен на уровне маршрута."
        )
    result["adjustments"] = adjustment.describe()
    return result


@router.get("/compare", summary="Прогноз рядом с фактом сопоставимого периода")
def compare(
    routes: str | None = Query(None),
    granularity: str = Query("day"),
) -> dict:
    if granularity not in aggregate.GRANULARITIES:
        raise ApiError(
            400, "INVALID_PARAMETER",
            f"granularity принимает значения hour, day или month. Получено: {granularity!r}",
        )
    dataset = get_dataset()
    return aggregate.compare_with_history(
        dataset,
        routes=parse_routes_param(routes),
        granularity=granularity,
        network=network_repository().effect(),
    )
