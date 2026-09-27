"""Sanity tests for the rolling forecasting pipeline.

    python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from src import astro, calendar_ru, config, events
from src.data import load_history
from src.models.cold_start import predict_new_routes
from src.pipeline import ForecastConfig, forecast


@pytest.fixture(scope="module")
def history():
    return load_history()


def production_cfg():
    return ForecastConfig.from_files(mode="production", ensemble={})


def test_astro_matches_open_meteo():
    observed = pd.read_csv(config.EXTERNAL / "daylight_moscow_2025.csv", parse_dates=["date"]).set_index("date")
    computed = astro.sun_times(observed.index)
    assert (computed.daylight_h - observed.daylight_h).abs().max() * 60 < 8  # minutes


def test_no_data_after_cutoff_is_used(history):
    cutoff = "2025-08-31"
    base = forecast(history, cutoff, "2025-09-01", "2025-09-30", production_cfg())
    poisoned = history.copy()
    poisoned.loc[poisoned.date > cutoff, "boardings"] *= 100  # any leak would change the forecast
    again = forecast(poisoned, cutoff, "2025-09-01", "2025-09-30", production_cfg())
    np.testing.assert_allclose(base.prediction, again.prediction)


def test_event_invisible_before_publication():
    assert events.get_network_state(5, "2025-12-20", 12, cutoff="2025-10-31") == []
    later = events.get_network_state(5, "2025-12-20", 12, cutoff="2025-12-31")
    assert [e["key"] for e in later] == ["route_5_new_route"]
    # launch hour respected: before 18:00 on the launch day the route is not running yet
    assert events.get_network_state(5, "2025-12-16", 10, cutoff="2025-12-31") == []


def test_production_mode_has_no_route5_before_launch_news(history):
    fc = forecast(history, "2025-10-31", "2025-11-01", "2025-12-31", production_cfg())
    assert fc[fc.route == 5].prediction.sum() == 0


def test_release_mode_reproduces_the_scored_forecast(history):
    """The release configuration rebuilds exactly the forecast that received the score (hash in release.json)."""
    import hashlib
    import json

    from ml.build_release import jury_csv_bytes

    rel = json.loads((config.ROOT / "configs" / "release.json").read_text(encoding="utf-8"))
    fc = forecast(history, "2025-10-31", "2025-11-01", "2025-12-31", ForecastConfig.from_files(mode=rel["mode"]))
    points = fc[["route", "date", "hour", "prediction"]].rename(columns={"prediction": "model_prediction"})
    points.loc[points.route.isin(rel["zero_routes"]), "model_prediction"] = 0.0
    points["model_prediction"] = points.model_prediction.round(3)
    points = points.sort_values(["route", "date", "hour"]).reset_index(drop=True)
    assert hashlib.md5(jury_csv_bytes(points)).hexdigest() == rel["scored_forecast"]["forecast_md5"]


def test_future_period_2026(history):
    fc = forecast(history, "2025-10-31", "2026-01-01", "2026-02-28", production_cfg())
    assert len(fc) == len(config.ROUTES) * 59 * 24
    assert fc.prediction.notna().all() and (fc.prediction >= 0).all()
    daily = fc[fc.route == 17].groupby("date").prediction.sum()
    # 5 Jan 2026 (Monday, official day off) must be far below 19 Jan (ordinary Monday)
    assert daily["2026-01-05"] < 0.7 * daily["2026-01-19"]
    # 1 January is much quieter than the other New-Year days off (estimated from January 2025)
    assert daily["2026-01-01"] < 0.6 * daily["2026-01-02"]


def test_calendar_coverage_is_enforced(history):
    with pytest.raises(ValueError):
        forecast(history, "2025-10-31", "2027-01-01", "2027-01-31", production_cfg())


def test_cold_start_takes_over_with_observations():
    keys = pd.DataFrame({"route": [5] * 24 + [25] * 24, "date": pd.Timestamp("2026-01-20"),
                         "hour": list(range(24)) * 2})
    keys["dow"] = keys.date.dt.dayofweek
    pred = np.where(keys.route == 25, 100.0, 0.0)
    prior = predict_new_routes(keys, pred, cutoff="2025-12-31")
    assert prior[keys.route == 5].sum() == pytest.approx(0.7 * 2400)
    # 14 observed days at 2x the prior -> estimate moves 2/3 of the way (14 / (14 + 7))
    days = pd.date_range("2025-12-17", "2025-12-30")
    hist = pd.concat([pd.DataFrame({"route": 25, "date": days, "boardings": 1000.0}),
                      pd.DataFrame({"route": 5, "date": days, "boardings": 1400.0})])
    post = predict_new_routes(keys, pred, history=hist, cutoff="2025-12-31")
    assert post[keys.route == 5].sum() == pytest.approx(0.7 * 2400 * (1 + 14 / 21))
