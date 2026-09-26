"""Build the read-only forecast release for the backend.

    python -m ml.build_release --data /data --output /data/forecast_release.duckdb
    python -m ml.build_release --output release/forecast_release.duckdb                  # repo defaults
    python -m ml.build_release --runtime /data/runtime.duckdb ...                         # + ingested aggregates

Steps: read data -> run the current model (src/pipeline.py) -> build forecast -> apply ZERO_ROUTES ->
check completeness -> write forecast_release.duckdb:

    release_metadata       one row: ids, cutoff, horizon, model version, score, code_git_sha, contents
    forecast_points        route, date, hour, model_prediction   (immutable base forecast)
    factor_options         what-if options: measured weather by season, demand-event scenarios
    network_impact_rules   secondary effects of network events — only measured ones (ml/transfer_experiment.py)
    forecast_intervals     optional: route, date, hour, p10, p90 (rolling-backtest residuals; --no-intervals skips)

Next to the .duckdb it also writes factor_options.csv / .json (catalog for the backend's factors.py) and,
with --submission, the jury CSV of exactly the same forecast values.

One release = one shown forecast: `score` is filled only if these exact values were scored (their md5 equals
configs/release.json -> scored_forecast.forecast_md5); `code_git_sha` is the commit that reproduces them
(suffix "-dirty" if the working tree had uncommitted changes; --require-clean refuses to build then).

--data: folder with labels/labels_day_train.csv, labels/labels_day_test.csv [, labels/*.csv extra months]
        [, test_submission.csv] [, external/ with the external sources]; defaults to the repository layout.
"""
import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL_PREDICTION_INCLUDES = [
    "historical route/day baseline (median of the last 4 clean weeks of the target's regime)",
    "hourly profile (median shares, school season)",
    "production calendar / day type (holiday -> Sunday level, working Saturday -> Friday, New-Year days)",
    "model seasonality (regime by target date, pre/post New-Year multipliers)",
    "daylight correction (half strength)",
    "route-specific known logic (routes 7 / 50 weekend repair regime)",
]
NOT_INCLUDED = ["user weather what-if", "user demand-event what-if", "user manual/season adjustment",
                "runtime network events"]


def git_sha():
    """HEAD commit of the repository, with '-dirty' if tracked or untracked files differ from it."""
    import subprocess
    run = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    head = run("rev-parse", "HEAD")
    if head.returncode:
        return None, True
    dirty = bool(run("status", "--porcelain", "--untracked-files=normal").stdout.strip())
    return head.stdout.strip(), dirty


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data folder (see module docstring)")
    ap.add_argument("--output", default=str(ROOT / "release" / "forecast_release.duckdb"))
    ap.add_argument("--runtime", help="runtime.duckdb whose hourly_aggregates extend the history")
    ap.add_argument("--cutoff", help="last history day (default: last day in the data)")
    ap.add_argument("--from", dest="start", help="first forecast day (default: cutoff + 1)")
    ap.add_argument("--to", dest="end", help="last forecast day (default: hackathon end or cutoff + 61 days)")
    ap.add_argument("--mode", choices=["leaderboard", "production"], help="default: configs/release.json")
    ap.add_argument("--release-id")
    ap.add_argument("--zero-routes", help='comma-separated routes forced to 0 ("" for none); default: configs/release.json')
    ap.add_argument("--no-intervals", action="store_true", help="skip the optional forecast_intervals table")
    ap.add_argument("--require-clean", action="store_true",
                    help="refuse to build unless the git working tree is clean (so code_git_sha reproduces it)")
    ap.add_argument("--submission", help="also write the jury CSV (route;date;hour;prediction) here")
    return ap.parse_args()


def configure_paths(data):
    """Point src.config at the data folder before src is imported."""
    if not data:
        return
    data = Path(data)
    os.environ["TRAM_DATASET"] = str(data)
    if (data / "external").exists():
        os.environ["TRAM_EXTERNAL"] = str(data / "external")


def read_runtime_aggregates(path):
    import duckdb
    import pandas as pd
    con = duckdb.connect(str(path), read_only=True)
    try:
        df = con.execute("SELECT route, date, hour, boardings FROM hourly_aggregates").df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df.date)
    return df


def check_completeness(points, routes, start, end, zero_routes):
    import pandas as pd
    n_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    expected = len(routes) * n_days * 24
    problems = []
    if len(points) != expected:
        problems.append(f"{len(points)} rows, expected {expected}")
    if points.duplicated(["route", "date", "hour"]).any():
        problems.append("duplicated keys")
    if points.model_prediction.isna().any():
        problems.append("NaN predictions")
    if (points.model_prediction < 0).any():
        problems.append("negative predictions")
    if set(points.route) != set(routes):
        problems.append(f"routes {sorted(set(points.route))} != {sorted(routes)}")
    if points[points.route.isin(zero_routes)].model_prediction.abs().sum() != 0:
        problems.append("zero routes are not zero")
    if problems:
        raise ValueError("release incomplete: " + "; ".join(problems))
    return expected


def jury_csv_bytes(points):
    """The jury CSV (route;date;hour;prediction) with LF line endings."""
    buf = io.StringIO()
    out = points[["route", "date", "hour", "model_prediction"]].rename(columns={"model_prediction": "prediction"})
    out = out.assign(date=out.date.dt.strftime("%Y-%m-%d"))
    out.to_csv(buf, sep=";", index=False, lineterminator="\n")
    return buf.getvalue().encode()


def release_score(csv_bytes, rel):
    """Score from configs/release.json, only if these exact forecast values are the scored ones."""
    scored = rel.get("scored_forecast") or {}
    digest = hashlib.md5(csv_bytes).hexdigest()
    return (scored.get("score"), digest) if digest == scored.get("forecast_md5") else (None, digest)


def build_intervals(history, cutoff, points):
    """Optional p10 / p90 per point: quantiles of actual / forecast from a rolling-origin backtest on the history
    (production configuration, no calibration), by horizon bucket and hour type (src/intervals.py)."""
    import pandas as pd

    from src import intervals
    from src.pipeline import ForecastConfig
    from src.rolling import DEFAULT_ORIGINS, evaluate_origins

    train = history[history.date <= cutoff]
    origins = [o for o in DEFAULT_ORIGINS if pd.Timestamp(o) < cutoff - pd.Timedelta(days=7)]
    res = evaluate_origins(train, ForecastConfig.from_files(mode="production", calibration="none"), origins=origins)
    table = intervals.fit(res.predictions)
    pts = points.assign(horizon=(points.date - cutoff).dt.days, prediction=points.model_prediction)
    iv = intervals.apply(pts, table)
    coverage = intervals.coverage_leave_one_origin_out(res.predictions)
    out = iv[["route", "date", "hour", "p10", "p90"]].copy()
    out[["p10", "p90"]] = out[["p10", "p90"]].round(3)
    return out, float(coverage.coverage.mean())


def write_duckdb(path, metadata, points, options, rules, intervals_table=None):
    import duckdb
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.duckdb")
    if tmp.exists():
        tmp.unlink()
    con = duckdb.connect(str(tmp))
    try:
        con.execute("""CREATE TABLE release_metadata (
            release_id VARCHAR, created_at TIMESTAMP, cutoff_date DATE, forecast_from DATE, forecast_to DATE,
            model_version VARCHAR, score DOUBLE, code_git_sha VARCHAR, schema_version VARCHAR,
            calibration VARCHAR, zero_routes VARCHAR,
            default_weather_factor DOUBLE, default_event_factor DOUBLE, default_season_factor DOUBLE,
            model_prediction_includes VARCHAR, not_included VARCHAR, n_points BIGINT, details VARCHAR)""")
        con.execute("INSERT INTO release_metadata SELECT * FROM metadata")
        con.execute("""CREATE TABLE forecast_points (route INTEGER, date DATE, hour INTEGER,
                       model_prediction DOUBLE, PRIMARY KEY (route, date, hour))""")
        con.execute("INSERT INTO forecast_points SELECT route, CAST(date AS DATE), hour, model_prediction FROM points")
        con.execute("""CREATE TABLE factor_options (factor_type VARCHAR, option_code VARCHAR, season VARCHAR,
                       value DOUBLE, label VARCHAR, source VARCHAR, is_measured BOOLEAN, n_days INTEGER,
                       ci_low DOUBLE, ci_high DOUBLE, significant BOOLEAN, confirmed BOOLEAN,
                       condition VARCHAR, method VARCHAR, PRIMARY KEY (factor_type, option_code, season))""")
        con.execute("INSERT INTO factor_options SELECT * FROM options")
        con.execute("""CREATE TABLE network_impact_rules (event_type VARCHAR, source_route INTEGER,
                       target_route INTEGER, factor DOUBLE, source VARCHAR)""")
        if len(rules):
            con.execute("INSERT INTO network_impact_rules SELECT * FROM rules")
        if intervals_table is not None:
            con.execute("""CREATE TABLE forecast_intervals (route INTEGER, date DATE, hour INTEGER,
                           p10 DOUBLE, p90 DOUBLE, PRIMARY KEY (route, date, hour))""")
            con.execute("INSERT INTO forecast_intervals SELECT route, CAST(date AS DATE), hour, p10, p90 "
                        "FROM intervals_table")
    finally:
        con.close()
    if path.exists():
        path.unlink()
    tmp.rename(path)  # atomic-ish replace: a failed build never leaves a half-written release


def main():
    args = parse_args()
    configure_paths(args.data)

    import pandas as pd

    from ml import factor_options, transfer_experiment
    from src import config
    from src.data import load_history
    from src.pipeline import ForecastConfig, forecast

    rel = json.loads((ROOT / "configs" / "release.json").read_text(encoding="utf-8"))
    mode = args.mode or rel["mode"]
    sha, dirty = git_sha()
    if args.require_clean and (sha is None or dirty):
        raise SystemExit("working tree is not a clean git commit: commit first, or drop --require-clean")
    code_git_sha = None if sha is None else sha + ("-dirty" if dirty else "")
    if args.zero_routes is not None:
        zero_routes = [int(r) for r in args.zero_routes.split(",") if r.strip()]
    else:
        zero_routes = [int(r) for r in rel.get("zero_routes", [])]

    extra = read_runtime_aggregates(args.runtime) if args.runtime else None
    history = load_history(extra=extra)
    cutoff = pd.Timestamp(args.cutoff) if args.cutoff else history.date.max()
    start = pd.Timestamp(args.start) if args.start else cutoff + pd.Timedelta(days=1)
    if args.end:
        end = pd.Timestamp(args.end)
    elif start == pd.Timestamp(config.FORECAST_START):
        end = pd.Timestamp(config.FORECAST_END)
    else:
        end = start + pd.Timedelta(days=60)

    cfg = ForecastConfig.from_files(mode=mode)
    fc = forecast(history, cutoff, start, end, cfg)
    points = fc[["route", "date", "hour", "prediction"]].rename(columns={"prediction": "model_prediction"})
    points.loc[points.route.isin(zero_routes), "model_prediction"] = 0.0
    points["model_prediction"] = points.model_prediction.round(3)
    points = points.sort_values(["route", "date", "hour"]).reset_index(drop=True)
    n = check_completeness(points, config.ROUTES, start, end, zero_routes)

    csv_bytes = jury_csv_bytes(points)
    score, forecast_md5 = release_score(csv_bytes, rel)
    train = history[history.date <= cutoff]
    options = factor_options.build(train)
    transfer = transfer_experiment.run() if cutoff >= pd.Timestamp("2025-10-31") else pd.DataFrame()
    rules = transfer_experiment.impact_rules(transfer) if len(transfer) else pd.DataFrame(
        columns=["event_type", "source_route", "target_route", "factor", "source"])

    intervals_table, coverage = (None, None) if args.no_intervals else build_intervals(history, cutoff, points)
    scale = cfg.leaderboard_scale if mode == "leaderboard" else 1.0
    calibration = f"x{scale} (final calibration, set on the test period)" if scale != 1.0 else "none"
    includes = list(MODEL_PREDICTION_INCLUDES)
    if scale != 1.0:
        includes.append(f"final calibration x{scale}")
    launched = [r for r in fc[fc.prediction > 0].route.unique() if r not in zero_routes
                and r not in set(history[history.date <= cutoff].query("boardings > 0").route)]
    if launched:
        includes.append(f"cold start of routes without history {sorted(int(r) for r in launched)} "
                        "(data/external/network_events.csv, new_route)")
    if zero_routes:
        includes.append(f"ZERO_ROUTES {zero_routes} forced to 0")
    metadata = pd.DataFrame([{
        "release_id": args.release_id or rel["release_id"], "created_at": datetime.now(),
        "cutoff_date": cutoff.date(), "forecast_from": start.date(), "forecast_to": end.date(),
        "model_version": rel["model_version"], "score": score, "code_git_sha": code_git_sha,
        "schema_version": rel["schema_version"], "calibration": calibration, "zero_routes": json.dumps(zero_routes),
        "default_weather_factor": 1.0, "default_event_factor": 1.0, "default_season_factor": 1.0,
        "model_prediction_includes": json.dumps(includes, ensure_ascii=False),
        "not_included": json.dumps(NOT_INCLUDED, ensure_ascii=False), "n_points": n,
        "details": json.dumps({"forecast_md5": forecast_md5, "model_params": cfg.model_params,
                               "history": [str(history.date.min().date()), str(cutoff.date())],
                               "runtime_aggregates_rows": 0 if extra is None else len(extra),
                               "transfer_experiment": "artifacts/transfer_experiment.md",
                               "forecast_intervals": None if intervals_table is None else {
                                   "table": "forecast_intervals", "nominal": "p10-p90 (80%)",
                                   "coverage_leave_one_origin_out": round(coverage, 3)},
                               "secondary_impacts": "enabled" if len(rules) else "disabled (no measured effect)"},
                              ensure_ascii=False, default=str),
    }])
    write_duckdb(args.output, metadata, points, options, rules, intervals_table)
    factor_options.export_catalog(options, Path(args.output).parent)
    if args.submission:
        Path(args.submission).write_bytes(csv_bytes)

    print(f"release {metadata.release_id[0]} -> {args.output}")
    print(f"  cutoff={cutoff.date()} forecast={start.date()}..{end.date()} points={n} zero_routes={zero_routes} "
          f"calibration={calibration}")
    print(f"  score={score} ({'scored forecast' if score is not None else 'these exact values were never scored'}, "
          f"md5 {forecast_md5}) code_git_sha={code_git_sha}")
    print(f"  factor_options={len(options)} (confirmed {int(options.confirmed.sum())}) "
          f"network_impact_rules={len(rules)}")


if __name__ == "__main__":
    main()
