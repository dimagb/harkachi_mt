"""Forecast from an arbitrary cutoff: history up to `cutoff` -> hourly boardings for [start, end].

    forecast(history, cutoff="2025-10-31", start="2025-11-01", end="2025-12-31", mode="production")

Layers (each one only sees information available at the cutoff):
    structural baseline      decomposition_v2: level(route, weekday) x hourly share, calendar mapping
    horizon / regime level   optional in decomposition_v2 (regime_by_target, horizon_weights)
    network state            src/events.py: events with published_at <= cutoff
    cold start               src/models/cold_start.py: new routes known at the cutoff
    calibration              "none" | "oof" (configs/oof_calibration.json) | "leaderboard" (x1.012)

Modes:
    production   known information only (events by published_at, no leaderboard numbers). Default.
    leaderboard  reproduces the hackathon submission: every event in the table regardless of publication
                 date (ex-post) and the leaderboard-calibrated scale.

Feature sources by availability (see SOURCE_AVAILABILITY): KNOWN_FUTURE may be used for any horizon;
FORECAST_FUTURE only as a forecast issued at the cutoff; UNKNOWN_FUTURE never in production.
"""
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import calendar_ru, config, events
from src.data import add_calendar_basics, make_grid
from src.factors import model_inputs
from src.models import cold_start
from src.models.decomp import decomposition_v2

SOURCE_AVAILABILITY = {
    "production_calendar": "KNOWN_FUTURE",
    "school_holidays": "KNOWN_FUTURE",
    "daylight": "KNOWN_FUTURE",
    "network_events (published_at <= cutoff)": "KNOWN_FUTURE",
    "weather_forecast": "FORECAST_FUTURE",
    "traffic_forecast": "FORECAST_FUTURE",
    "actual_weather": "UNKNOWN_FUTURE",
    "vehicles_in_service (garage_number, bus_exit_no)": "UNKNOWN_FUTURE",
    "network_events (published_at > cutoff)": "UNKNOWN_FUTURE",
}

HORIZON_BUCKETS = [(1, 7), (8, 14), (15, 30), (31, 60), (61, 90)]


@dataclass
class ForecastConfig:
    model_params: dict = field(default_factory=dict)
    mode: str = "production"               # production | leaderboard
    calibration: str | None = None         # None -> "leaderboard" in leaderboard mode, "none" otherwise
    leaderboard_scale: float = 1.0
    oof_calibration: dict | None = None    # {"1-7": ratio, ...}
    new_routes: bool = True
    routes: tuple = tuple(config.ROUTES)

    @classmethod
    def from_files(cls, mode="production", **overrides):
        """Model parameters from configs/final_model.json; the leaderboard scale is kept separately."""
        final = json.loads((config.ROOT / "configs" / "final_model.json").read_text(encoding="utf-8"))
        params = dict(final["params"])
        scale = params.pop("scale", 1.0)
        oof_path = config.ROOT / "configs" / "oof_calibration.json"
        oof = json.loads(oof_path.read_text(encoding="utf-8")) if oof_path.exists() else None
        return cls(model_params=params, mode=mode, leaderboard_scale=scale, oof_calibration=oof, **overrides)


def horizon_bucket(h):
    for lo, hi in HORIZON_BUCKETS:
        if lo <= h <= hi:
            return f"{lo}-{hi}"
    return f">{HORIZON_BUCKETS[-1][1]}"


def forecast(history, cutoff, start, end, cfg=None, factors=None):
    """Hourly forecast for [start, end] using only `history` rows dated <= cutoff.

    history: full grid with route, date, hour, boardings (src.data.load_history()).
    factors: precomputed src.factors.model_inputs(train); computed from train when omitted.
    Returns keys (route, date, hour, dow, horizon) + prediction.
    """
    cfg = cfg or ForecastConfig.from_files()
    cutoff, start, end = pd.Timestamp(cutoff), pd.Timestamp(start), pd.Timestamp(end)
    if start <= cutoff:
        raise ValueError("forecast must start after the cutoff")
    calendar_ru.check_coverage(pd.date_range(start, end))
    train = history[history.date <= cutoff]
    if train.empty:
        raise ValueError("no history up to the cutoff")

    keys = add_calendar_basics(make_grid(start, end, list(cfg.routes)))
    factors = factors or model_inputs(train)
    params = dict(cfg.model_params,
                  day_mult=calendar_ru.day_mult_from_factors(factors),
                  working_weekend_mult=factors["calendar"]["preholiday"]["value"])
    pred = decomposition_v2(**params)(train, keys)

    event_cutoff = cutoff if cfg.mode == "production" else None  # leaderboard mode: ex-post events
    if cfg.new_routes:
        pred = cold_start.predict_new_routes(keys, pred, history=train, cutoff=event_cutoff)
    pred = events.apply_multipliers(keys, pred, event_cutoff)

    keys["horizon"] = (keys.date - cutoff).dt.days
    calibration = cfg.calibration or ("leaderboard" if cfg.mode == "leaderboard" else "none")
    if calibration == "leaderboard":
        pred = pred * cfg.leaderboard_scale
    elif calibration == "oof":
        if not cfg.oof_calibration:
            raise ValueError("configs/oof_calibration.json is missing; run scripts/rolling_backtest.py")
        ratio = keys.horizon.map(horizon_bucket).map(cfg.oof_calibration).fillna(1.0).to_numpy()
        pred = pred * ratio
    return keys.assign(prediction=np.clip(pred, 0, None))
