"""What-if options for the UI (table factor_options of forecast_release.duckdb + factor_options.csv/.json).

WEATHER options are measured on history (src/factors.py::weather_factors): day volume vs the same route and
weekday in ±21 days, relative to dry days of the same season. The effect depends on the season (summer rain
cancels leisure trips, cold-season rain barely matters), so every option is tied to a season:
    warm = April–September, cold = October–March.
An option exists for a season only if it was measured there (>= 3 days).
    significant  the 90% bootstrap interval excludes 1
    confirmed    measured AND significant — only these may be presented as a proven external effect

EVENT (demand-event) options: no event data was measured, so MEDIUM / MAJOR are explicit manual scenarios
(confirmed = false). Season and manual sliders are not options: backend computes factor = 1 + pct / 100.
"""
import json

import pandas as pd

from src.factors import prepare, weather_factors

WARM_MONTHS = (4, 5, 6, 7, 8, 9)
SEASON_OF_MONTH = {m: ("warm" if m in WARM_MONTHS else "cold") for m in range(1, 13)}
SEASONS = {"warm": "апрель–сентябрь", "cold": "октябрь–март", "all": "весь год"}

# option_code -> (factor key prefix in weather_factors, label)
WEATHER = {
    "RAIN_LIGHT": ("rain_light", "Небольшой дождь (0.5–3 мм за день)"),
    "RAIN": ("rain_moderate", "Дождь (3–10 мм)"),
    "RAIN_HEAVY": ("rain_heavy", "Сильный дождь (≥ 10 мм)"),
    "SNOW": ("snowfall", "Снегопад (≥ 1 см)"),
    "HEAT": ("heat", "Жара (≥ 25 °C днём)"),
}
EVENT_MANUAL = {
    "MEDIUM": (1.05, "Среднее событие у линии (ручной сценарий)"),
    "MAJOR": (1.15, "Крупное событие у линии (ручной сценарий)"),
}
WEATHER_METHOD = ("Open-Meteo ERA5 (архив, Москва 55.75, 37.62), осадки/снег/температура за 06–21 ч. "
                  "Для каждого чистого дня маршрута (без праздников и аномалий): суточные посадки / медиана того же "
                  "маршрута и дня недели в ±21 день; сумма по маршрутам в дни с условием ÷ сумма ожиданий, "
                  "нормированная на такое же отношение в сухие дни того же сезона. 90% интервал — бутстреп по датам. "
                  "История января–октября 2025 (src/factors.py::weather_factors).")


def _row(factor_type, code, season, value, label, source, measured, n=None, lo=None, hi=None, condition=None,
         method=None):
    significant = bool(measured and lo is not None and (hi < 1 or lo > 1))
    return {"factor_type": factor_type, "option_code": code, "season": season, "value": value, "label": label,
            "source": source, "is_measured": measured, "n_days": n, "ci_low": lo, "ci_high": hi,
            "significant": significant, "confirmed": bool(measured and significant),
            "condition": condition, "method": method}


def build(history):
    daily, hourly = prepare(history)
    measured = weather_factors(daily, hourly)
    rows = [_row("WEATHER", "NORMAL", s, 1.0, "Обычная погода", "definition", False,
                 method="нейтральное значение по определению") for s in ("warm", "cold")]
    for code, (key, label) in WEATHER.items():
        for season in ("warm", "cold"):
            f = measured.get(f"{key}_{season}")
            if not f:
                continue  # not measured in this season -> no option
            lo, hi = f["ci90"]
            rows.append(_row("WEATHER", code, season, f["value"], label, f"measured: {f['source']}", True,
                             f["n_dates"], lo, hi, f.get("condition"), WEATHER_METHOD))
    rows.append(_row("EVENT", "NONE", "all", 1.0, "Нет события", "definition", False,
                     method="нейтральное значение по определению"))
    for code, (value, label) in EVENT_MANUAL.items():
        rows.append(_row("EVENT", code, "all", value, label, "manual_scenario", False,
                         method="не измерено: данных о массовых событиях нет; ручная гипотеза для сценария"))
    return pd.DataFrame(rows)


def export_catalog(options, folder):
    """factor_options.csv / .json next to the release: the catalog for the backend's factors.py.
    factor_code == factor_type; scope == season (warm = апрель–сентябрь, cold = октябрь–март, all)."""
    cat = options.rename(columns={"factor_type": "factor_code"}).assign(
        scope=lambda d: d.season.map(SEASONS))
    cols = ["factor_code", "option_code", "season", "scope", "value", "label", "source", "confirmed",
            "is_measured", "significant", "n_days", "ci_low", "ci_high", "condition", "method"]
    cat = cat[cols]
    cat.to_csv(folder / "factor_options.csv", index=False, encoding="utf-8")
    records = json.loads(cat.to_json(orient="records", force_ascii=False))
    (folder / "factor_options.json").write_text(json.dumps(
        {"seasons": {"warm": list(WARM_MONTHS), "cold": [m for m in range(1, 13) if m not in WARM_MONTHS]},
         "options": records}, ensure_ascii=False, indent=2), encoding="utf-8")
