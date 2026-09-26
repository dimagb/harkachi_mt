"""Factors estimated from history.

- weather_factors: measured weather effects by season -> what-if options (ml/factor_options.py);
- model_inputs: the few estimated numbers the forecast itself uses (pre-holiday day, New-Year days).

Every factor is `treated volume / reference volume`, where the reference for a route-day is the median
of the same route and weekday on clean ordinary days (no holiday, anomaly, event) within ±21 days.
"""
import numpy as np
import pandas as pd

from src import calendar_ru, config, events
from src.models.decomp import flag_anomalies
from src.weather import load_daily as load_daily_weather

WINDOW_DAYS = 21
MIN_DATES_BY_ROUTE = 5       # distinct treated dates needed before a route gets its own factor
SHRINK_DATES = 3             # route factor = (n*route + k*global) / (n + k)
BY_HOUR_MIN_SPREAD = 0.15    # hourly factors must differ by at least this much (hours 6–21) ...
BY_HOUR_SIGNAL_TO_NOISE = 2  # ... and the spread must exceed this many median hourly 90% CI widths
HOURS_REPORTED = range(5, 24)
N_BOOT = 300
RNG = np.random.default_rng(0)


# ------------------------------------------------------------------ preparation
def prepare(history):
    """Daily route table with calendar, anomaly and event flags + hourly table."""
    daily = history.groupby(["route", "date", "dow"], as_index=False).boardings.sum()
    daily = daily.rename(columns={"boardings": "day"})
    daily = flag_anomalies(calendar_ru.annotate(daily, use_school=True))
    daily["event"] = events.active(daily, as_of=pd.Timestamp("2100-01-01"))
    daily["clean"] = ~daily.is_special & ~daily.is_anomaly & ~daily.event & ~daily.is_school_holiday
    daily = daily[daily.route != 5]  # no data for route 5
    hourly = history[history.route != 5][["route", "date", "hour", "boardings"]]
    return daily, hourly


def _pairs(treated, candidates, same_dow=True, window=WINDOW_DAYS):
    """(treated route-date) x (reference route-date) pairs within the window, excluding the day itself."""
    keys = ["route", "dow"] if same_dow else ["route"]
    p = treated[["route", "date", "dow"]].merge(
        candidates[["route", "date", "dow"]].rename(columns={"date": "ref_date"}), on=keys)
    gap = (p.ref_date - p.date).dt.days.abs()
    return p[(gap <= window) & (gap > 0)]


def _estimate(treated, pairs, daily, hourly):
    """Per treated route-date: actual day, reference day, actual & reference by hour."""
    ref_day = pairs.merge(daily[["route", "date", "day"]].rename(columns={"date": "ref_date"}),
                          on=["route", "ref_date"]).groupby(["route", "date"]).day.median().rename("ref")
    t = treated[["route", "date", "day"]].join(ref_day, on=["route", "date"]).dropna()
    t = t[t.ref > 0]
    h_ref = (pairs.merge(hourly.rename(columns={"date": "ref_date"}), on=["route", "ref_date"])
             .groupby(["route", "date", "hour"]).boardings.median().rename("ref_h"))
    h = hourly.merge(t[["route", "date"]], on=["route", "date"]).join(h_ref, on=["route", "date", "hour"])
    return t, h.fillna({"ref_h": 0})


def _ratio(num, den):
    return float(num.sum() / den.sum()) if den.sum() > 0 else np.nan


def _boot(t, stat, n=N_BOOT):
    dates = t.date.unique()
    vals = []
    for _ in range(n):
        pick = pd.Series(RNG.choice(dates, len(dates)))
        vals.append(stat(t.merge(pick.rename("date").to_frame(), on="date")))
    return np.nanpercentile(vals, [5, 95])


def factor_from(t, h, *, method, source, allow_by_hour=True, extra=None):
    """Builds the factor dict with the value / by_route / by_hour hierarchy."""
    value = _ratio(t.day, t.ref)
    lo, hi = _boot(t, lambda d: _ratio(d.day, d.ref))
    out = {"value": round(value, 4), "ci90": [round(lo, 4), round(hi, 4)],
           "n_dates": int(t.date.nunique()), "n_route_days": int(len(t)),
           "method": method, "source": source}

    by_route = {}
    for route, g in t.groupby("route"):
        n = g.date.nunique()
        if n >= MIN_DATES_BY_ROUTE:
            r = _ratio(g.day, g.ref)
            by_route[str(route)] = round((n * r + SHRINK_DATES * value) / (n + SHRINK_DATES), 4)
    if by_route:
        out["by_route"] = by_route

    if allow_by_hour:
        hh = h[h.hour.isin(HOURS_REPORTED)]
        hour_vals = hh.groupby("hour").apply(lambda g: _ratio(g.boardings, g.ref_h), include_groups=False)
        core = hour_vals[hour_vals.index.isin(range(6, 22))]
        spread = float(core.max() - core.min())
        widths = []
        for hour in core.index:
            g = hh[hh.hour == hour].rename(columns={"boardings": "day", "ref_h": "ref"})
            lo_h, hi_h = _boot(g, lambda d: _ratio(d.day, d.ref), n=100)
            widths.append(hi_h - lo_h)
        noise = float(np.median(widths))
        out["by_hour_check"] = {
            "spread_6_21": round(spread, 3), "median_ci90_width": round(noise, 3),
            "included": bool(spread >= BY_HOUR_MIN_SPREAD and spread >= BY_HOUR_SIGNAL_TO_NOISE * noise)}
        if out["by_hour_check"]["included"]:
            out["by_hour"] = {str(k): round(float(v), 4) for k, v in hour_vals.items()}
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------------------ individual factors
def weather_factors(daily, hourly):
    raw = pd.read_csv(config.EXTERNAL / "weather_moscow_2025_hourly.csv", parse_dates=["date"])
    day = raw[raw.hour.between(6, 21)].groupby("date").agg(
        snow=("snowfall", "sum"), temp=("temperature_2m", "mean"))
    normal = daily[daily.clean]
    d = normal.join(load_daily_weather(), on="date").join(day, on="date")
    src = "Open-Meteo archive (ERA5), data/external/weather_moscow_2025_hourly.csv"

    # Reference days include all weather, so every condition is normalised by the dry-day ratio.
    dry_days = d[(d.precip < 0.5) & (d.snow < 0.5)]
    t0, _ = _estimate(dry_days, _pairs(dry_days, normal), daily, hourly)
    dry = _ratio(t0.day, t0.ref)
    conditions = {
        "rain_light": ((d.precip >= 0.5) & (d.precip < 3) & (d.snow < 0.5), "осадки 0.5–3 мм за 06–21 ч"),
        "rain_moderate": ((d.precip >= 3) & (d.precip < 10) & (d.snow < 0.5), "осадки 3–10 мм за 06–21 ч"),
        "rain_heavy": ((d.precip >= 10) & (d.snow < 0.5), "осадки ≥ 10 мм за 06–21 ч"),
        "snowfall": (d.snow >= 1.0, "снегопад ≥ 1 см за 06–21 ч"),
        "frost": (d.temp <= -10, "средняя температура 06–21 ч ≤ −10 °C"),
        "heat": (d.temp >= 25, "средняя температура 06–21 ч ≥ 25 °C"),
    }
    # The effect depends on the season: summer rain cancels leisure trips (-5%), cold-season rain barely
    # matters (-1%). So every condition is also estimated per season, normalised by that season's dry days.
    seasons = {"": d.date.notna(),
               "_warm": d.date.dt.month.isin([4, 5, 6, 7, 8, 9]),
               "_cold": d.date.dt.month.isin([1, 2, 3, 10, 11, 12])}
    res = {}
    for suffix, in_season in seasons.items():
        s_dry = d[in_season & (d.precip < 0.5) & (d.snow < 0.5)]
        t0, _ = _estimate(s_dry, _pairs(s_dry, normal), daily, hourly)
        dry_s = _ratio(t0.day, t0.ref) if suffix else dry
        for name, (mask, condition) in conditions.items():
            tr = d[mask & in_season]
            if tr.date.nunique() < 3:  # too few days to estimate anything
                continue
            t, h = _estimate(tr, _pairs(tr, normal), daily, hourly)
            season_txt = {"": "все сезоны", "_warm": "апрель–сентябрь", "_cold": "октябрь–март"}[suffix]
            res[name + suffix] = factor_from(
                t.assign(ref=t.ref * dry_s), h.assign(ref_h=h.ref_h * dry_s), source=src,
                method=f"день ÷ тот же день недели ±21 дн., нормировано на сухие дни сезона ({season_txt})",
                extra={"condition": condition, "season": season_txt, "dry_day_ratio": round(dry_s, 4)})
    return res


def model_inputs(history):
    """Only the two estimated numbers the forecast itself needs (no bootstrap, fast):
    calendar.preholiday and seasonality.new_year_week_*. Falls back to calendar_ru constants when the
    history has no analog days yet (e.g. an early cutoff)."""
    daily, hourly = prepare(history)
    normal = daily[daily.clean]

    def ratio(dates):
        tr = daily[daily.date.isin(pd.to_datetime(dates))]
        if tr.empty:
            return None
        t, _ = _estimate(tr, _pairs(tr, normal), daily, hourly)
        return _ratio(t.day, t.ref) if len(t) else None

    pre = ratio(daily.loc[daily.date.isin(calendar_ru._cal.date[calendar_ru._cal.day_type == "preholiday"]), "date"])
    ny = {}
    for name, days, default in [("new_year_week_weekday", (9, 10), calendar_ru.PRE_NEW_YEAR_WEEKDAY),
                                ("new_year_week_weekend", (11, 12), calendar_ru.PRE_NEW_YEAR_WEEKEND)]:
        # the working days / weekend right after the January holidays of each observed year
        dates = [pd.Timestamp(y, 1, d) for y in daily.date.dt.year.unique() for d in days]
        v = ratio(dates)
        ny[name] = {"value": round(v, 4) if v and np.isfinite(v) else default}
    ny.update(_new_year_holiday_factors(daily))
    return {"calendar": {"preholiday": {"value": round(pre, 4) if pre and np.isfinite(pre) else 1.0}},
            "seasonality": ny}


def _new_year_holiday_factors(daily):
    """New-Year holidays relative to an ordinary Sunday (the level the model already uses for days off):
    1 January separately (people sleep in), the rest of the official New-Year days off together.
    Reference: median Sunday of clean days 13 Jan – 9 Feb of the same year. Uses the latest January seen."""
    out = {"new_year_day": {"value": 1.0}, "new_year_holidays": {"value": 1.0}}
    years = sorted(daily.date.dt.year[daily.date.dt.month == 1].unique())
    for y in years[-1:]:
        ref_days = daily[daily.clean & (daily.dow == 6) & daily.date.between(f"{y}-01-13", f"{y}-02-09")]
        ref = ref_days.groupby("route").day.median()
        if ref.empty:
            continue
        ny_days = daily[daily.date.between(f"{y}-01-01", f"{y}-01-12") & (daily.is_day_off | daily.is_block_weekend)]
        for name, part in [("new_year_day", ny_days[ny_days.date == f"{y}-01-01"]),
                           ("new_year_holidays", ny_days[ny_days.date > f"{y}-01-01"])]:
            r = part.day.sum() / part.route.map(ref).sum() if len(part) else np.nan
            if np.isfinite(r):
                out[name] = {"value": round(float(r), 4), "year": int(y), "n_days": int(part.date.nunique())}
    return out
