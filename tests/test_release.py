"""The forecast release built for the backend (python -m ml.build_release).

    python -m pytest tests/test_release.py -q      (~1 minute: builds a full release)
"""
import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    folder = tmp_path_factory.mktemp("rel")
    out = folder / "forecast_release.duckdb"
    subprocess.run([sys.executable, "-m", "ml.build_release", "--output", str(out)], cwd=ROOT, check=True,
                   capture_output=True)
    assert (folder / "factor_options.csv").exists() and (folder / "factor_options.json").exists()
    con = duckdb.connect(str(out), read_only=True)
    yield con
    con.close()


def test_tables(release):
    tables = {r[0] for r in release.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    required = {"release_metadata", "forecast_points", "factor_options", "network_impact_rules"}
    assert required <= tables and tables - required <= {"forecast_intervals"}


def test_intervals_bracket_the_forecast(release):
    n, inside, zero_ok = release.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE i.p10 <= p.model_prediction AND p.model_prediction <= i.p90),
               count(*) FILTER (WHERE p.model_prediction > 0 OR (i.p10 = 0 AND i.p90 = 0))
        FROM forecast_points p JOIN forecast_intervals i USING (route, date, hour)""").fetchone()
    assert n == 14640 and inside == n and zero_ok == n


def test_metadata(release):
    m = release.execute("SELECT * FROM release_metadata").df().iloc[0]
    rel = json.loads((ROOT / "configs" / "release.json").read_text(encoding="utf-8"))
    assert m.release_id == rel["release_id"] and m.schema_version == rel["schema_version"]
    assert (m.default_weather_factor, m.default_event_factor, m.default_season_factor) == (1.0, 1.0, 1.0)
    assert m.n_points == 14640
    assert m.code_git_sha  # commit that reproduces the release ("-dirty" if built from uncommitted code)
    # one release = one shown forecast: the score belongs to exactly these values
    assert m.score == pytest.approx(rel["scored_forecast"]["score"])


def test_forecast_points_complete(release):
    n, dup, neg, nulls = release.execute("""
        SELECT count(*), count(*) - count(DISTINCT (route, date, hour)),
               count(*) FILTER (WHERE model_prediction < 0), count(*) FILTER (WHERE model_prediction IS NULL)
        FROM forecast_points""").fetchone()
    assert (n, dup, neg, nulls) == (14640, 0, 0, 0)


def test_zero_routes(release):
    zero = json.loads((ROOT / "configs" / "release.json").read_text(encoding="utf-8"))["zero_routes"]
    for r in zero:
        assert release.execute("SELECT sum(model_prediction) FROM forecast_points WHERE route = ?", [r]).fetchone()[0] == 0


def test_factor_options_only_measured_or_labelled(release):
    df = release.execute("SELECT * FROM factor_options").df()
    ok_source = df.source.str.startswith("measured") | df.source.isin(["definition", "manual_scenario"])
    assert ok_source.all()
    assert (df[df.source == "definition"].value == 1.0).all()
    # measured options carry their evidence; significance is consistent with the interval
    meas = df[df.is_measured]
    assert meas.n_days.notna().all() and meas.method.notna().all()
    assert ((meas.ci_high < 1) | (meas.ci_low > 1)).eq(meas.significant).all()
    # only measured + significant options count as a confirmed external effect
    assert df.confirmed.eq(df.is_measured & df.significant).all()
    assert not df[df.source == "manual_scenario"].confirmed.any()
    # weather effect is season-specific: no global option, NORMAL for both seasons
    weather = df[df.factor_type == "WEATHER"]
    assert set(weather.season) == {"warm", "cold"}


def test_secondary_effects_are_only_published_measurements(release):
    """Every network_impact_rule must be a published row of the transfer experiment (no invented effects)."""
    from ml.transfer_experiment import run
    published = run().query("published")
    rules = release.execute("SELECT event_type, source_route, target_route, factor FROM network_impact_rules").df()
    assert len(rules) == len(published)
    merged = rules.merge(published, on=["event_type", "source_route", "target_route"])
    assert len(merged) == len(rules)
    assert (merged.factor == merged.effect_median).all()
