"""Daily weather features (external source #3, Open-Meteo ERA5; see scripts/fetch_weather.py)."""
import numpy as np
import pandas as pd

from src import config

PRECIP_CAP = 15.0  # mm; a handful of extreme days should not drive the slope


def load_daily():
    w = pd.read_csv(config.EXTERNAL / "weather_moscow_2025_hourly.csv", parse_dates=["date"])
    day = w[w.hour.between(6, 21)].groupby("date").agg(precip=("precipitation", "sum"))
    day["precip"] = day.precip.clip(upper=PRECIP_CAP)
    return day


CONDITIONS = [  # (name, test on daily weather); first match wins
    ("snow", lambda w: w.snow >= 2.0),
    ("frost", lambda w: w.temp <= -10),
    ("rain_heavy", lambda w: (w.precip >= 10) & (w.snow < 0.5)),
    ("rain_moderate", lambda w: (w.precip >= 3) & (w.precip < 10) & (w.snow < 0.5)),
]


def load_daily_full():
    """Daytime (06–21) precipitation, snowfall and mean temperature per date."""
    w = pd.read_csv(config.EXTERNAL / "weather_moscow_2025_hourly.csv", parse_dates=["date"])
    return w[w.hour.between(6, 21)].groupby("date").agg(
        precip=("precipitation", "sum"), snow=("snowfall", "sum"), temp=("temperature_2m", "mean"))


def classify(weather_daily):
    cond = pd.Series("normal", index=weather_daily.index)
    for name, test in reversed(CONDITIONS):  # reversed so that the first condition overrides
        cond[test(weather_daily)] = name
    return cond


def extreme_factors(daily, weather_daily, shrink=5, min_days=3):
    """Multiplier per (condition, weekend) from clean train days: sum(day)/sum(ref), relative to normal days,
    shrunk towards 1 by n/(n+shrink). `daily` comes from decomp.flag_anomalies (has day, ref)."""
    d = daily[~daily.is_special & ~daily.is_anomaly & daily.ref.gt(0)].copy()
    d["cond"] = d.date.map(classify(weather_daily)).fillna("normal")
    d["we"] = d.dow >= 5
    base = d[d.cond == "normal"].groupby("we").apply(lambda g: g.day.sum() / g.ref.sum(), include_groups=False)
    out = {}
    for (cond, we), g in d[d.cond != "normal"].groupby(["cond", "we"]):
        n = g.date.nunique()
        if n < min_days:
            g = d[d.cond == cond]  # pool weekdays and weekends
            n = g.date.nunique()
            if n < min_days:
                continue
        f = (g.day.sum() / g.ref.sum()) / base.get(we, 1.0)
        out[(cond, we)] = 1 + (f - 1) * n / (n + shrink)
    return out


def fit_precip_slope(daily, weather):
    """OLS through the origin of log(day / ref) on daytime precipitation, over clean train days.

    `daily` is the output of decomp.flag_anomalies (has day, ref, is_special, is_anomaly).
    """
    d = daily[~daily.is_special & ~daily.is_anomaly & daily.ref.gt(0) & daily.day.gt(0)]
    tot = d.groupby("date").agg(day=("day", "sum"), ref=("ref", "sum")).join(weather, how="inner")
    res = np.log(tot.day / tot.ref)
    x = tot.precip - tot.precip.mean()
    return float((x * (res - res.mean())).sum() / (x ** 2).sum()), float(tot.precip.mean())
