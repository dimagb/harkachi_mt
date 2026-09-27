"""Release snapshot safety, event revisions and hybrid demand/share semantics."""
import hashlib
import json
import numpy as np
import pandas as pd
import pytest

from src import config, events
from src.data import load_history
from src.pipeline import ForecastConfig, forecast
from src.models import chronos_ensemble as hybrid


def test_restoration_revision_is_visible_only_after_publication():
    def end(cutoff):
        row = events.known(cutoff).query("key == 'route_50_weekend_suspended'").iloc[0]
        return row.valid_to
    assert end("2025-10-31") == pd.Timestamp("2025-11-30 23:59")
    assert end("2025-11-15") == pd.Timestamp("2025-11-14 23:59:59")
    assert end(None) == pd.Timestamp("2025-11-14 23:59:59")
    with events.information_set(None):
        assert end("2025-10-31") == end(None)
    assert end("2025-10-31") == pd.Timestamp("2025-11-30 23:59")


def test_hybrid_preserves_daily_total_and_route5_prior():
    base = pd.DataFrame({"route": [1]*24+[5]*24, "date": pd.Timestamp("2025-12-20"),
                         "hour": list(range(24))*2, "prediction": [100.]*24+[70.]*24})
    day = pd.DataFrame({"route": [1], "date": pd.Timestamp("2025-12-20"), "foundation_day": [4800.]})
    hour = base[base.route == 1][["route", "date", "hour"]].assign(foundation_hour=np.arange(1,25)*10.)
    out = hybrid.blend(base, day, hour)
    assert out[out.route == 1].prediction.sum() == pytest.approx(3000.)
    np.testing.assert_array_equal(out[out.route == 5].prediction, base[base.route == 5].prediction)
    assert out.loc[23, "prediction"] > out.loc[0, "prediction"]
    with pytest.raises(ValueError, match="missing Chronos"):
        hybrid.blend(base, day, hour.iloc[:-1])


def test_frozen_components_reject_changed_history(monkeypatch):
    history = load_history()
    changed = history.copy();changed.loc[0, "boardings"] += 1
    def no_reuse(*args, **kwargs):
        raise RuntimeError("fresh inference required")
    monkeypatch.setattr(hybrid, "infer", no_reuse)
    cfg = ForecastConfig.from_files(mode="leaderboard")
    hybrid.components(history, "2025-10-31", "2025-12-31", cfg)
    with pytest.raises(RuntimeError, match="fresh inference required"):
        hybrid.components(changed, "2025-10-31", "2025-12-31", cfg)
    poisoned = pd.concat([history, history.iloc[:24].assign(date=pd.Timestamp("2025-11-02"), boardings=1e9)])
    assert hybrid.history_digest(history, "2025-10-31") == hybrid.history_digest(poisoned, "2025-10-31")


def test_snapshot_production_forecast_has_no_post_cutoff_target_leak():
    history = load_history()
    cfg = ForecastConfig.from_files(mode="production")
    expected = forecast(history, "2025-10-31", "2025-11-01", "2025-12-31", cfg)
    poisoned = pd.concat([history, history.iloc[:24].assign(date=pd.Timestamp("2025-11-02"), boardings=1e9)])
    actual = forecast(poisoned, "2025-10-31", "2025-11-01", "2025-12-31", cfg)
    np.testing.assert_array_equal(expected.prediction, actual.prediction)
    assert expected[expected.route == 5].prediction.sum() == 0


def test_published_submission_and_service_are_exactly_same():
    rel = json.loads((config.ROOT / "configs/release.json").read_text(encoding="utf-8"))
    payload = (config.ROOT / "release/submission.csv").read_bytes()
    assert payload == (config.ROOT / "service/data/submission.csv").read_bytes()
    assert hashlib.md5(payload).hexdigest() == rel["scored_forecast"]["forecast_md5"]
    frame = pd.read_csv(config.ROOT / "release/submission.csv", sep=";", parse_dates=["date"])
    before = (frame.date + pd.to_timedelta(frame.hour, unit="h")) < pd.Timestamp("2025-12-16 18:00")
    assert frame.loc[(frame.route == 5) & before, "prediction"].sum() == 0
    assert frame.loc[(frame.route == 5) & ~before, "prediction"].sum() > 0
