"""Rolling-origin temporal evaluation: many cutoffs x horizon buckets, strictly no data after the cutoff.

    res = evaluate_origins(history, cfg, origins=[...], max_horizon=60)
    res.summary        one row per bucket: pooled WAPE-score, mean over origins, bias, n origins
    res.by_origin      origin x bucket
    res.slices         origin x (route | daytype | hour_bucket) x horizon bucket
    res.predictions    all forecasts with actuals

Everything a forecast uses is filtered by the cutoff: history rows (date <= cutoff) inside
src.pipeline.forecast, network events by published_at <= cutoff in production mode.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.pipeline import HORIZON_BUCKETS, forecast, horizon_bucket

DEFAULT_ORIGINS = ["2025-02-28", "2025-03-31", "2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31",
                   "2025-08-31", "2025-09-30"]
EVAL_BUCKETS = [b for b in HORIZON_BUCKETS if b[1] <= 60]


def wape_score(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return 1 - np.abs(y - p).sum() / y.sum() if y.sum() > 0 else np.nan


@dataclass
class RollingResult:
    summary: pd.DataFrame
    by_origin: pd.DataFrame
    slices: pd.DataFrame
    predictions: pd.DataFrame

    def headline(self):
        """Compact row: overall + per-bucket pooled WAPE-score and overall bias."""
        s = self.summary.set_index("bucket")
        row = {"overall": s.loc["all", "wape_score"], "bias": s.loc["all", "bias"]}
        row.update({b: s.loc[b, "wape_score"] for b in s.index if b != "all"})
        return row


def _bucket_table(df, keys):
    g = df.groupby(keys)
    return pd.DataFrame({"wape_score": g.apply(lambda x: wape_score(x.boardings, x.prediction), include_groups=False),
                         "bias": g.prediction.sum() / g.boardings.sum() - 1,
                         "volume": g.boardings.sum()}).reset_index()


def evaluate_origins(history, cfg, origins=DEFAULT_ORIGINS, max_horizon=60, forecaster=forecast):
    parts = []
    last = history.date.max()
    for origin in pd.to_datetime(origins):
        end = min(origin + pd.Timedelta(days=max_horizon), last)
        if end <= origin:
            continue
        f = forecaster(history, origin, origin + pd.Timedelta(days=1), end, cfg)
        actual = history[(history.date > origin) & (history.date <= end)]
        f = f.merge(actual[["route", "date", "hour", "boardings"]], on=["route", "date", "hour"])
        parts.append(f.assign(origin=origin))
    pred = pd.concat(parts, ignore_index=True)
    pred["bucket"] = pred.horizon.map(horizon_bucket)
    pred["daytype"] = np.select([pred.dow < 5, pred.dow == 5], ["weekday", "sat"], "sun")
    pred["hour_bucket"] = np.select(
        [pred.hour.between(6, 9), pred.hour.between(10, 15), pred.hour.between(16, 19), pred.hour.between(20, 23)],
        ["am_peak", "day", "pm_peak", "evening"], "night")

    by_origin = pd.concat([_bucket_table(pred, ["origin", "bucket"]),
                           _bucket_table(pred.assign(bucket="all"), ["origin", "bucket"])])
    pooled = pd.concat([_bucket_table(pred, ["bucket"]), _bucket_table(pred.assign(bucket="all"), ["bucket"])])
    mean_over_origins = by_origin.groupby("bucket").wape_score.agg(["mean", "min", "count"]).rename(
        columns={"mean": "mean_over_origins", "min": "worst_origin", "count": "n_origins"})
    summary = pooled.join(mean_over_origins, on="bucket")
    order = [f"{lo}-{hi}" for lo, hi in EVAL_BUCKETS] + ["all"]
    summary = summary.set_index("bucket").reindex([b for b in order if b in set(summary.bucket)]).reset_index()
    slices = pd.concat([_bucket_table(pred, ["origin", "bucket", c]).rename(columns={c: "value"}).assign(slice=c)
                        for c in ["route", "daytype", "hour_bucket"]], ignore_index=True)
    return RollingResult(summary, by_origin, slices, pred)
