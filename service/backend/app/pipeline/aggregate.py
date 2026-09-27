"""Агрегация прогноза.

Третье звено цепочки. Отвечает на запросы вида «дай прогноз по маршруту 17
за первую неделю декабря с шагом в час» и раскладывает маршрутный прогноз по
остановкам.

Горизонты:
    hour  — почасовой (краткосрочный, день)
    day   — посуточный (среднесрочный, месяц)
    month — помесячный (долгосрочный, год; история + прогноз)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app import config
from app.pipeline import geo as geo_module
from app.pipeline.adjust import Adjustment
from app.pipeline.ingest import Dataset, RowIndex
from app.pipeline.network_events import NetworkEffect

GRANULARITIES = ("hour", "day", "month")


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _bucket_label(key: str, granularity: str) -> str:
    if granularity == "hour":
        return key.replace("T", " ") + ":00"
    return key


def iter_rows(
    index: RowIndex,
    *,
    routes=None,
    start: date | None = None,
    end: date | None = None,
    hour_from: int | None = None,
    hour_to: int | None = None,
    adjustment: Adjustment | None = None,
    network: NetworkEffect | None = None,
):
    """Строки среза с пересчитанным значением: (строка индекса, значение).

    Часы None — фильтра по часам нет вовсе (как в сводке по маршрутам).

    Порядок пересчёта: база → поправки пользователя → события сети.
    События последними: закрытие обнуляет результат независимо от любых
    коэффициентов (раздел 26 контракта). Поправки считаются, только если
    они заданы, события — только для маршрутов, у которых они есть.
    Порядок строк исходный.
    """
    adjust = adjustment is not None and not adjustment.is_identity
    event_routes = network.routes if network is not None else ()
    check_hours = hour_from is not None
    rows = index.rows
    for pos in index.positions(routes, start, end):
        row = rows[pos]
        hour = row[2]
        if check_hours and (hour < hour_from or hour > hour_to):
            continue
        value = row[3]
        if adjust:
            value = value * adjustment.factor(row[0], row[1])
        if row[0] in event_routes:
            value = network.apply(row[0], row[1], hour, value)
        yield row, value


def series(
    dataset: Dataset,
    *,
    routes: list | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    hour_from: int = 0,
    hour_to: int = 23,
    granularity: str = "hour",
    source: str = "forecast",
    adjustment: Adjustment | None = None,
    split_by_route: bool = False,
    network: NetworkEffect | None = None,
) -> dict:
    """Основная выборка. Возвращает ряд точек и сводку."""
    if granularity not in GRANULARITIES:
        granularity = "hour"

    # События сети — про будущее, к фактической истории они не относятся.
    if source != "forecast":
        network = None

    index = dataset.forecast_index if source == "forecast" else dataset.history_index
    available = dataset.forecast_dates if source == "forecast" else dataset.history_dates
    if not available:
        return {
            "granularity": granularity,
            "source": source,
            "points": [],
            "summary": {"total": 0.0, "peak": None, "rows": 0},
            "adjustments": [],
            "network_events": [],
        }

    start = date_from or min(available)
    end = date_to or max(available)
    wanted_routes = set(routes) if routes else None

    totals: dict = defaultdict(float)
    per_route: dict = defaultdict(lambda: defaultdict(float))
    peak = None
    rows = 0

    key_position = RowIndex.KEY_POSITION[granularity]
    for row, value in iter_rows(
        index,
        routes=wanted_routes,
        start=start,
        end=end,
        hour_from=hour_from,
        hour_to=hour_to,
        adjustment=adjustment,
        network=network,
    ):
        route, day, hour = row[0], row[1], row[2]
        key = row[key_position]
        totals[key] += value
        if split_by_route:
            per_route[route][key] += value
        rows += 1
        if peak is None or value > peak["value"]:
            peak = {
                "route": route,
                "date": day.isoformat(),
                "hour": hour,
                "value": round(value, 2),
            }

    points = [
        {
            "key": key,
            "label": _bucket_label(key, granularity),
            "value": round(totals[key], 2),
        }
        for key in sorted(totals)
    ]

    result = {
        "granularity": granularity,
        "source": source,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "hours": {"from": hour_from, "to": hour_to},
        "routes": sorted(wanted_routes) if wanted_routes else dataset.routes,
        "points": points,
        "summary": {
            "total": round(sum(totals.values()), 2),
            "peak": peak,
            "rows": rows,
            "buckets": len(points),
        },
        "adjustments": adjustment.describe() if adjustment else [],
        "network_events": (
            network.relevant(sorted(wanted_routes) if wanted_routes else None, start, end)
            if network is not None
            else []
        ),
    }

    # Ключ появляется только при действующем вторичном эффекте: без событий
    # ответ байт в байт прежний.
    if network is not None:
        secondary = network.secondary_effects(
            sorted(wanted_routes) if wanted_routes else None, start, end
        )
        if secondary:
            result["secondary_effects"] = secondary

    if split_by_route:
        result["by_route"] = {
            str(route): [
                {"key": key, "value": round(values[key], 2)}
                for key in sorted(values)
            ]
            for route, values in sorted(per_route.items())
        }
    return result


def route_totals(
    dataset: Dataset,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    adjustment: Adjustment | None = None,
    network: NetworkEffect | None = None,
) -> list:
    """Сводка по маршрутам за период — для карты и списка слева."""
    available = dataset.forecast_dates
    if not available:
        return []
    start = date_from or min(available)
    end = date_to or max(available)

    totals: dict = defaultdict(float)
    peaks: dict = {}
    for row, value in iter_rows(
        dataset.forecast_index,
        start=start,
        end=end,
        adjustment=adjustment,
        network=network,
    ):
        route, day, hour = row[0], row[1], row[2]
        totals[route] += value
        current = peaks.get(route)
        if current is None or value > current["value"]:
            peaks[route] = {
                "date": day.isoformat(),
                "hour": hour,
                "value": round(value, 2),
            }

    geo = geo_module.get_geo()
    grand_total = sum(totals.values()) or 1.0
    output = []
    for route in config.ROUTES:
        total = totals.get(route, 0.0)
        output.append(
            {
                "route": route,
                "total": round(total, 2),
                "share": round(total / grand_total, 4),
                "peak": peaks.get(route),
                "has_geometry": geo.has_geometry(route),
                "excluded": route in config.EXCLUDED_ROUTES,
            }
        )
    return output


def by_stop(
    dataset: Dataset,
    route: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    hour_from: int = 0,
    hour_to: int = 23,
    adjustment: Adjustment | None = None,
    network: NetworkEffect | None = None,
) -> dict:
    """Разложение маршрутного прогноза по остановкам.

    ВНИМАНИЕ: оценочное. Целевая величина задачи определена на уровне
    «маршрут × час», привязки валидаций к остановкам в данных нет.
    Доли берутся из профиля формы маршрута (см. geo.stop_shares).
    """
    geo = geo_module.get_geo()
    shares = geo.stop_shares(route)
    stops = geo.stops(route)

    available = dataset.forecast_dates
    start = date_from or (min(available) if available else None)
    end = date_to or (max(available) if available else None)

    total = 0.0
    for _row, value in iter_rows(
        dataset.forecast_index,
        routes=[route],
        start=start,
        end=end,
        hour_from=hour_from,
        hour_to=hour_to,
        adjustment=adjustment,
        network=network,
    ):
        total += value

    items = []
    for stop in stops:
        share = shares.get(stop.stop_id, 0.0)
        payload = stop.as_dict()
        payload["value"] = round(total * share, 2)
        payload["share"] = round(share, 4)
        items.append(payload)

    return {
        "route": route,
        "period": {
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
        },
        "total": round(total, 2),
        "stops": items,
        "estimated": True,
        "method": "распределение по профилю формы маршрута",
        "note": (
            "Оценка. В данных нет привязки валидаций к остановкам: "
            "place_id — это код депо. Модель прогнозирует на уровне "
            "маршрут × час, разложение по точкам приблизительное."
        ),
    }


def compare_with_history(
    dataset: Dataset,
    *,
    routes: list | None = None,
    granularity: str = "day",
    network: NetworkEffect | None = None,
) -> dict:
    """Прогноз рядом с фактом за сопоставимый прошлый период.

    Прямого пересечения нет (история заканчивается там, где начинается
    прогноз), поэтому для сравнения берётся столько же последних дней истории.
    """
    if not dataset.forecast_dates or not dataset.history_dates:
        return {"forecast": [], "history": []}

    horizon_days = (max(dataset.forecast_dates) - min(dataset.forecast_dates)).days
    history_end = max(dataset.history_dates)
    history_start = history_end - timedelta(days=horizon_days)

    forecast = series(
        dataset,
        routes=routes,
        granularity=granularity,
        source="forecast",
        network=network,
    )
    history = series(
        dataset,
        routes=routes,
        date_from=history_start,
        date_to=history_end,
        granularity=granularity,
        source="history",
    )
    return {"forecast": forecast, "history": history}
