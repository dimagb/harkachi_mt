"""Эндпойнты прогноза: выборка по маршруту, остановке, интервалу и горизонту."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app.api.deps import adjustment_params, parse_date_param, parse_routes_param
from app.pipeline import aggregate
from app.pipeline.adjust import Adjustment
from app.pipeline.ingest import get_dataset

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
        raise HTTPException(
            status_code=400,
            detail=(
                "horizon принимает значения day, month или year. "
                f"Получено: {horizon!r}"
            ),
        )
    if hour_from > hour_to:
        raise HTTPException(
            status_code=400,
            detail="hour_from не может быть больше hour_to",
        )
    if source not in ("forecast", "history"):
        raise HTTPException(
            status_code=400,
            detail="source принимает значения forecast или history",
        )

    step = granularity or HORIZON_TO_GRANULARITY[horizon]
    dataset = get_dataset()
    result = aggregate.series(
        dataset,
        routes=parse_routes_param(routes),
        date_from=parse_date_param(date_from, "date_from"),
        date_to=parse_date_param(date_to, "date_to"),
        hour_from=hour_from,
        hour_to=hour_to,
        granularity=step,
        source=source,
        adjustment=adjustment,
        split_by_route=split_by_route,
    )
    result["horizon"] = horizon
    return result


@router.get("/routes", summary="Сводка по маршрутам за период")
def forecast_by_routes(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    adjustment: Adjustment = Depends(adjustment_params),
) -> dict:
    dataset = get_dataset()
    return {
        "period": {"from": date_from, "to": date_to},
        "routes": aggregate.route_totals(
            dataset,
            date_from=parse_date_param(date_from, "date_from"),
            date_to=parse_date_param(date_to, "date_to"),
            adjustment=adjustment,
        ),
        "adjustments": adjustment.describe(),
    }


@router.get("/stops", summary="Разложение прогноза по остановкам (оценочное)")
def forecast_by_stops(
    route: int = Query(..., description="Номер маршрута"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    adjustment: Adjustment = Depends(adjustment_params),
) -> dict:
    if route not in config.ROUTES:
        raise HTTPException(
            status_code=404,
            detail=f"Маршрут {route} не входит в набор задачи: {config.ROUTES}",
        )
    dataset = get_dataset()
    result = aggregate.by_stop(
        dataset,
        route,
        date_from=parse_date_param(date_from, "date_from"),
        date_to=parse_date_param(date_to, "date_to"),
        hour_from=hour_from,
        hour_to=hour_to,
        adjustment=adjustment,
    )
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
    dataset = get_dataset()
    return aggregate.compare_with_history(
        dataset,
        routes=parse_routes_param(routes),
        granularity=granularity,
    )
