"""Empirical prediction intervals from rolling-origin residuals.

For every (horizon bucket, hour bucket) the quantiles of actual / forecast are taken over the rolling
backtest (rows with forecast >= MIN_PRED; tiny night-time forecasts give meaningless ratios). The interval
for a new forecast is forecast x those quantiles. Output goes to an optional file next to the contract
(forecast_intervals.csv); submission.csv is untouched.
"""
import numpy as np
import pandas as pd

from src.pipeline import horizon_bucket

MIN_PRED = 20.0
QUANTILES = (0.1, 0.9)


def hour_bucket(hour):
    return np.select([hour.between(6, 9), hour.between(10, 15), hour.between(16, 19), hour.between(20, 23)],
                     ["am_peak", "day", "pm_peak", "evening"], "night")


def fit(predictions, quantiles=QUANTILES):
    """predictions: RollingResult.predictions (horizon, hour, prediction, boardings)."""
    p = predictions[predictions.prediction >= MIN_PRED].copy()
    p["bucket"] = p.horizon.map(horizon_bucket)
    p["hb"] = hour_bucket(p.hour)
    p["ratio"] = p.boardings / p.prediction
    table = p.groupby(["bucket", "hb"]).ratio.quantile(list(quantiles)).unstack()
    table.columns = [f"q{int(q * 100)}" for q in quantiles]
    return table


def apply(fc, table):
    """fc: forecast frame with horizon, hour, prediction -> adds p10 / p90 (or the fitted quantiles)."""
    out = fc.copy()
    key = pd.MultiIndex.from_arrays([out.horizon.map(horizon_bucket), hour_bucket(out.hour)])
    for q in table.columns:
        # beyond the backtested horizons use the longest bucket available
        vals = table[q].reindex(key)
        fallback = table[q].xs(table.index.get_level_values(0)[-1], level=0)
        vals = vals.fillna(pd.Series(hour_bucket(out.hour), index=vals.index).map(fallback))
        out[q.replace("q", "p")] = (out.prediction * vals.to_numpy()).clip(lower=0)
    return out


def coverage_leave_one_origin_out(predictions, quantiles=QUANTILES):
    """Share of actuals inside the interval when the interval is fitted on the other origins."""
    rows = []
    for origin, test in predictions.groupby("origin"):
        table = fit(predictions[predictions.origin != origin], quantiles)
        iv = apply(test, table)
        lo, hi = iv.columns[-2], iv.columns[-1]
        big = iv.prediction >= MIN_PRED
        inside = (iv.boardings >= iv[lo]) & (iv.boardings <= iv[hi])
        rows.append({"origin": origin, "coverage": inside[big].mean(),
                     "rel_width": ((iv[hi] - iv[lo]) / iv.prediction)[big].median()})
    return pd.DataFrame(rows)
