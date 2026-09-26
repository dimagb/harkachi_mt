"""POST /api/forecast/preview — сценарий именованными опциями (раздел 39).

Тонкая обёртка над той же агрегацией, что GET /api/forecast с k_*:
опции переводятся в Adjustment, база и сценарий считаются одним кодом.
Сценарий всегда строится от неизменного model_prediction.

Погода — только опции каталога ML-релиза (release/factor_options.json)
для сезона дат запроса: warm — апрель–сентябрь, cold — октябрь–март.
Опции, которой для сезона нет, нет и в сценарии: 400, а не выдуманный
коэффициент. Неподтверждённая (измерена, но незначима) — с пометкой.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.api.deps import ApiError, check_period, check_route, parse_date_param
from app.pipeline import aggregate
from app.pipeline.adjust import Adjustment
from app.pipeline.ingest import get_dataset
from app.pipeline.network_events import get_repository as network_repository

router = APIRouter(prefix="/forecast", tags=["прогноз"])

PCT_RANGE = (-90.0, 400.0)   # множитель 0.1–5.0, как у k_* в GET


class PreviewIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    route: int | None = None
    routes: list[int] | None = None
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    weather: str = "NORMAL"
    event: str = "NONE"
    season_adjustment_pct: float = 0.0
    manual_adjustment_pct: float = 0.0


def _catalog() -> dict:
    try:
        return json.loads(config.FACTOR_OPTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _season_of(month: int, catalog: dict) -> str:
    seasons = catalog.get("seasons") or {"warm": [4, 5, 6, 7, 8, 9]}
    return "warm" if month in seasons.get("warm", []) else "cold"


def _option(catalog: dict, factor: str, code: str, season: str) -> dict | None:
    for opt in catalog.get("options", []):
        if opt.get("factor_code") == factor and opt.get("option_code") == code \
                and opt.get("season") in (season, "all"):
            return opt
    return None


def _pct(value: float, name: str) -> float:
    low, high = PCT_RANGE
    if not low <= value <= high:
        raise ApiError(400, "INVALID_SCENARIO", f"{name} — от {low:g} до {high:g} %, получено: {value:g}")
    return 1 + value / 100


@router.post("/preview", summary="Сценарий именованными опциями (раздел 39)")
def preview(body: PreviewIn) -> dict:
    dataset = get_dataset()
    if not dataset.forecast:
        raise ApiError(503, "FORECAST_NOT_LOADED", "Прогноз не загружен: нет файла submission.csv")

    routes = body.routes or ([body.route] if body.route is not None else None)
    for r in routes or []:
        check_route(r)
    start = parse_date_param(body.from_, "from") or dataset.forecast_dates[0]
    end = parse_date_param(body.to, "to") or dataset.forecast_dates[-1]
    warnings = check_period(dataset, "forecast", start, end)

    catalog = _catalog()
    weather_code = body.weather.strip().upper()
    event_code = body.event.strip().upper()
    seasons = {_season_of(m, catalog) for m in {start.month, end.month}}
    if len(seasons) > 1:
        raise ApiError(
            400, "INVALID_SCENARIO",
            "Период захватывает тёплый и холодный сезоны — погодный коэффициент "
            "у них разный. Разбейте период по границе сезона",
        )
    season = seasons.pop()

    weather = {"code": "NORMAL", "value": 1.0, "season": season, "confirmed": None, "label": "Обычная погода"}
    if weather_code != "NORMAL":
        opt = _option(catalog, "WEATHER", weather_code, season)
        if opt is None:
            known = sorted({o["option_code"] for o in catalog.get("options", [])
                            if o.get("factor_code") == "WEATHER" and o.get("season") == season})
            raise ApiError(
                400, "INVALID_SCENARIO",
                f"Погодной опции {weather_code} для сезона {season} в каталоге релиза нет"
                + (f"; есть: {', '.join(known)}" if known else "")
                + ". Для ноября–декабря подтверждённых погодных коэффициентов нет вообще",
            )
        weather = {"code": weather_code, "value": opt["value"], "season": season,
                   "confirmed": opt.get("confirmed"), "label": opt.get("label")}
        if not opt.get("confirmed"):
            warnings.append(
                f"Погода {weather_code} для сезона {season}: коэффициент {opt['value']} "
                "измерен, но незначим — это не подтверждённый эффект"
            )

    event = {"code": "NONE", "value": 1.0, "confirmed": None, "label": "Нет события"}
    if event_code != "NONE":
        opt = _option(catalog, "EVENT", event_code, season)
        if opt is None:
            raise ApiError(400, "INVALID_SCENARIO", f"Опции события {event_code} в каталоге релиза нет")
        event = {"code": event_code, "value": opt["value"], "confirmed": opt.get("confirmed"),
                 "label": opt.get("label")}
        if not opt.get("confirmed"):
            warnings.append(f"Событие {event_code}: ручная гипотеза, данных о массовых событиях нет")

    season_k = _pct(body.season_adjustment_pct, "season_adjustment_pct")
    manual_k = _pct(body.manual_adjustment_pct, "manual_adjustment_pct")
    adjustment = Adjustment(
        weather=weather["value"], weather_from=start, weather_to=end,
        event=event["value"], event_from=start, event_to=end,
        global_factor=season_k * manual_k,
    )

    network = network_repository().effect()
    granularity = "hour" if start == end else "day"
    kwargs = dict(routes=routes, date_from=start, date_to=end, granularity=granularity, network=network)
    base = aggregate.series(dataset, **kwargs)
    scenario = aggregate.series(dataset, adjustment=adjustment, **kwargs)
    b, s = base["summary"]["total"], scenario["summary"]["total"]

    result = {
        "routes": routes,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "scenario_inputs": {
            "weather": weather,
            "event": event,
            "season_adjustment_pct": body.season_adjustment_pct,
            "manual_adjustment_pct": body.manual_adjustment_pct,
        },
        # Раздел 42: из чего сложился результат, без SHAP.
        "explain": [
            {"step": "Прогноз (с событиями сети)", "total": b},
            {"step": f"Погода {weather['code']}", "factor": weather["value"]},
            {"step": f"Событие {event['code']}", "factor": event["value"]},
            {"step": "Сезонная поправка", "factor": round(season_k, 6)},
            {"step": "Ручная поправка", "factor": round(manual_k, 6)},
            {"step": "Сценарий", "total": s},
        ],
        "base": base,
        "scenario": scenario,
        "difference_pct": round((s - b) / b * 100, 2) if b else None,
    }
    if warnings:
        result["warnings"] = warnings
    return result
