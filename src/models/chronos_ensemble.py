"""Chronos-2 daily-demand/hourly-share ensemble promoted from temporal experiments.

Published component snapshots reproduce the scored window without PyTorch/network.
Changed history or another window requires fresh inference; snapshots are never
silently reused for new observations. No target rows after cutoff enter the model.
"""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src import astro, calendar_ru, config, events

ARTIFACTS = config.ROOT / "artifacts" / "chronos"
MODEL_ID = "amazon/chronos-2"
REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def history_digest(history, cutoff):
    frame = history.loc[history.date <= pd.Timestamp(cutoff), ["route", "date", "hour", "boardings"]]
    frame = frame.sort_values(["route", "date", "hour"]).copy()
    frame["date"] = frame.date.dt.strftime("%Y-%m-%d")
    return hashlib.sha256(frame.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()).hexdigest()


def source_digests():
    paths = {f"data/external/{name}": config.EXTERNAL / name for name in
             ["network_events.csv", "production_calendar.csv", "school_holidays_moscow.csv", "daylight_moscow_2025.csv"]}
    paths.update({f"src/{name}": config.ROOT / "src" / name for name in ["calendar_ru.py", "astro.py", "events.py"]})
    return {name:
            hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name,path in paths.items()}


def covariates(dates, route, cutoff):
    frame = pd.DataFrame({"date": pd.DatetimeIndex(dates), "route": route})
    frame["dow"] = frame.date.dt.dayofweek
    frame = calendar_ru.annotate(frame, use_school=True)
    return {
        "weekday": frame.eff_dow.astype(str).to_numpy(),
        "summer": frame.is_summer.astype(np.float32).to_numpy(),
        "holiday": frame.is_special.astype(np.float32).to_numpy(),
        "daylight": astro.daylight_table(dates).daylight_h.to_numpy(dtype=np.float32),
        "event": np.asarray(events.active(frame, pd.Timestamp(cutoff) + pd.Timedelta(days=1)), dtype=np.float32),
    }


def load_pipeline(model_path=None):
    cache = config.ROOT / ".ml-cache"
    for key, name in [("HF_HOME", "huggingface"), ("TORCH_HOME", "torch"),
                      ("TORCHINDUCTOR_CACHE_DIR", "torchinductor"), ("TRITON_CACHE_DIR", "triton"),
                      ("MPLCONFIGDIR", "mpl")]:
        os.environ[key] = str(cache / name)
    os.environ.update(HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_XET="1",
                      HF_HUB_DISABLE_SYMLINKS_WARNING="1")
    try:
        import torch
        from chronos import Chronos2Pipeline
    except ImportError as exc:
        raise RuntimeError("Fresh Chronos inference requires requirements-foundation.txt; "
                           "the scored window can use artifacts/chronos snapshots offline.") from exc
    torch.set_num_threads(4)
    return Chronos2Pipeline.from_pretrained(
        model_path or MODEL_ID, revision=None if model_path else REVISION,
        device_map="cpu", dtype=torch.float32, cache_dir=str(cache / "huggingface" / "hub"))


def infer(history, cutoff, end, pipe=None):
    """Same zero-shot median predictions and batching as the scored experiment."""
    cutoff, end = pd.Timestamp(cutoff), pd.Timestamp(end)
    train = history[history.date <= cutoff]
    routes = sorted(r for r in train.route.unique() if r != 5)
    dates = pd.date_range(train.date.min(), cutoff)
    future = pd.date_range(cutoff + pd.Timedelta(days=1), end)
    if not len(future):
        raise ValueError("empty foundation forecast horizon")
    pipe = pipe or load_pipeline()
    median = list(pipe.quantiles).index(.5)
    grouped = train.groupby(["route", "date"], as_index=False).boardings.sum()
    matrix = grouped.pivot(index="date", columns="route", values="boardings")[routes].fillna(0)
    values = matrix.to_numpy(dtype=np.float32).T
    inputs = [{"target": values[i], "past_covariates": covariates(matrix.index, route, cutoff),
               "future_covariates": covariates(future, route, cutoff)} for i, route in enumerate(routes)]
    outputs = pipe.predict(inputs, prediction_length=len(future), context_length=512,
                           batch_size=100, cross_learning=True)
    daily = pd.DataFrame(np.stack([p[0, median, :].numpy() for p in outputs]), index=routes, columns=future)
    daily = daily.stack().rename("foundation_day").reset_index()
    daily.columns = ["route", "date", "foundation_day"]
    inputs = []
    for route in routes:
        values = train[train.route == route].pivot(index="hour", columns="date", values="boardings")
        values = values.reindex(index=range(24), columns=dates).fillna(0).to_numpy(dtype=np.float32)
        inputs.append({"target": values, "past_covariates": covariates(dates, route, cutoff),
                       "future_covariates": covariates(future, route, cutoff)})
    outputs = pipe.predict(inputs, prediction_length=len(future), context_length=512, batch_size=100)
    parts = []
    for route, output in zip(routes, outputs):
        frame = pd.DataFrame(output[:, median, :].numpy(), index=range(24), columns=future)
        frame = frame.stack().rename("foundation_hour").reset_index()
        frame.columns = ["hour", "date", "foundation_hour"]
        frame["route"] = route
        parts.append(frame)
    return daily, pd.concat(parts, ignore_index=True)


def export_snapshot(history, cutoff, end, mode, daily, hourly):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    stem = f"{mode}_20251031"
    frame = hourly.merge(daily, on=["route", "date"], validate="many_to_one")
    path = ARTIFACTS / f"{stem}.csv"
    frame.sort_values(["route", "date", "hour"]).to_csv(path, index=False, float_format="%.17g", lineterminator="\n")
    meta = {"model": MODEL_ID, "revision": REVISION, "mode": mode,
            "cutoff": str(pd.Timestamp(cutoff).date()), "end": str(pd.Timestamp(end).date()),
            "history_sha256": history_digest(history, cutoff), "sources_sha256": source_digests(),
            "components_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "target_availability": "only organizer labels <= cutoff; no future transport targets",
            "known_future": "calendar and astronomy; network announcements follow information mode",
            "context_length": 512, "daily_cross_learning": True, "hourly_channels": 24,
            "quantile": .5, "training": "frozen pretrained zero-shot, no private-target fine tuning"}
    (ARTIFACTS / f"{stem}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def components(history, cutoff, end, cfg):
    stem = f"{cfg.mode}_20251031"
    manifest, path = ARTIFACTS / f"{stem}.json", ARTIFACTS / f"{stem}.csv"
    if not cfg.recompute_foundation and manifest.exists() and path.exists():
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        matches = (str(pd.Timestamp(cutoff).date()) == meta["cutoff"]
                   and str(pd.Timestamp(end).date()) == meta["end"]
                   and history_digest(history, cutoff) == meta["history_sha256"]
                   and source_digests() == meta["sources_sha256"]
                   and cfg.ensemble.get("revision", REVISION) == meta["revision"])
        if matches:
            if hashlib.sha256(path.read_bytes()).hexdigest() != meta["components_sha256"]:
                raise ValueError("Chronos component snapshot checksum mismatch")
            frame = pd.read_csv(path, parse_dates=["date"], float_precision="round_trip",
                                dtype={"foundation_day": "float32", "foundation_hour": "float32"})
            daily = frame[["route", "date", "foundation_day"]].drop_duplicates()
            return daily, frame[["route", "date", "hour", "foundation_hour"]]
    return infer(history, cutoff, end)


def blend(base, daily, hourly, daily_weight=.25, shape_weight=.25):
    """Blend daily totals and normalized hourly shares independently; route 5 retains its prior."""
    if not (0 <= daily_weight <= 1 and 0 <= shape_weight <= 1):
        raise ValueError("ensemble weights must be between zero and one")
    frame = base.merge(daily, on=["route", "date"], how="left", validate="many_to_one")
    frame = frame.merge(hourly, on=["route", "date", "hour"], how="left", validate="one_to_one")
    missing = (frame.foundation_day.isna() | frame.foundation_hour.isna()) & (frame.route != 5)
    if missing.any():
        raise ValueError("missing Chronos components for modeled route/hour")
    frame["foundation_hour"] = frame.foundation_hour.fillna(frame.prediction).clip(lower=0)
    bd = frame.groupby(["route", "date"]).prediction.transform("sum").to_numpy()
    hd = frame.groupby(["route", "date"]).foundation_hour.transform("sum").to_numpy()
    ratio = np.divide(frame.foundation_day.fillna(pd.Series(bd)).to_numpy(), bd,
                      out=np.ones(len(frame)), where=bd > 100).clip(.25, 2.)
    bs = np.divide(frame.prediction.to_numpy(), bd, out=np.zeros(len(frame)), where=bd > 0)
    hs = np.divide(frame.foundation_hour.to_numpy(), hd, out=bs.copy(), where=hd > 0)
    prediction = bd * (1 - daily_weight + daily_weight * ratio) * ((1 - shape_weight) * bs + shape_weight * hs)
    prediction[frame.route.to_numpy() == 5] = frame.loc[frame.route == 5, "prediction"]
    return base.assign(prediction=prediction)


def apply(base, history, cutoff, end, cfg):
    if cfg.ensemble.get("revision", REVISION) != REVISION:
        raise ValueError("unsupported foundation model revision")
    daily, hourly = components(history, cutoff, end, cfg)
    calibration = cfg.calibration or ("leaderboard" if cfg.mode == "leaderboard" else "none")
    scale = cfg.leaderboard_scale if calibration == "leaderboard" else 1.
    raw = base.copy()
    raw["prediction"] /= scale
    output = blend(raw, daily, hourly, cfg.ensemble.get("daily_weight", .25), cfg.ensemble.get("shape_weight", .25))
    output["prediction"] *= scale
    return output
