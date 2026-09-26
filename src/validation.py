"""Time-series backtesting. A model never sees data at or after the fold origin."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fold:
    name: str
    train_start: str
    origin: str      # first forecast day; history is strictly before it
    horizon_end: str
    weight: float


FOLDS = [
    Fold("A", "2025-01-01", "2025-09-01", "2025-10-31", 0.35),  # same 61-day horizon, origin after summer
    Fold("B", "2025-01-01", "2025-10-01", "2025-10-31", 0.35),  # stable school-season origin, like the final one
    Fold("C", "2025-01-15", "2025-03-01", "2025-04-30", 0.15),  # stable origin, long horizon
    Fold("D", "2025-01-15", "2025-05-01", "2025-06-30", 0.15),  # May/June holidays
]
SANITY_FOLDS = [Fold("E", "2025-01-15", "2025-07-01", "2025-08-31", 0.0)]  # summer, not used for selection


def wape_score(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return max(0.0, 1.0 - np.abs(y - p).sum() / y.sum())


def bias(y, p):
    return np.asarray(p, float).sum() / np.asarray(y, float).sum() - 1.0


def split(history, fold):
    train = history[(history.date >= fold.train_start) & (history.date < fold.origin)]
    target = history[(history.date >= fold.origin) & (history.date <= fold.horizon_end)]
    return train, target


def _hour_bucket(h):
    return np.select(
        [h.between(6, 9), h.between(10, 15), h.between(16, 19), h.between(20, 23)],
        ["am_peak", "day", "pm_peak", "evening"], "night",
    )


def slices(frame, fold):
    """frame: target rows with boardings and pred."""
    f = frame.assign(
        route=frame.route.astype(str),
        daytype=np.select([frame.dow < 5, frame.dow == 5], ["weekday", "sat"], "sun"),
        hour_bucket=_hour_bucket(frame.hour),
        horizon_week=((frame.date - pd.Timestamp(fold.origin)).dt.days // 7).astype(str),
    )
    rows = []
    for col in ["route", "daytype", "hour_bucket", "horizon_week"]:
        for val, g in f.groupby(col):
            if g.boardings.sum() == 0:
                continue
            rows.append({"fold": fold.name, "slice": col, "value": val,
                         "wape_score": wape_score(g.boardings, g.pred), "bias": bias(g.boardings, g.pred),
                         "volume": g.boardings.sum()})
    return pd.DataFrame(rows)


def backtest(predict, history, folds=FOLDS):
    """predict(train, target_keys) -> array aligned with target_keys rows.

    target_keys carries no target column, so the model cannot peek at the horizon.
    Returns (scores per fold, predictions, slices).
    """
    scores, preds, sl = [], [], []
    if not folds:
        empty = pd.DataFrame(columns=["fold", "wape_score", "bias", "weight"])
        return empty, pd.DataFrame(columns=["fold", "route", "date", "hour", "boardings", "pred"]), pd.DataFrame()
    for fold in folds:
        train, target = split(history, fold)
        keys = target.drop(columns=["boardings"]).reset_index(drop=True)
        p = np.clip(np.asarray(predict(train, keys), float), 0, None)
        frame = target.reset_index(drop=True).assign(pred=p, fold=fold.name)
        scores.append({"fold": fold.name, "wape_score": wape_score(frame.boardings, p),
                       "bias": bias(frame.boardings, p), "weight": fold.weight})
        preds.append(frame)
        sl.append(slices(frame, fold))
    return pd.DataFrame(scores), pd.concat(preds, ignore_index=True), pd.concat(sl, ignore_index=True)


def weighted_score(scores):
    s = scores[scores.weight > 0]
    return float((s.wape_score * s.weight).sum() / s.weight.sum())
