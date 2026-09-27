"""Verify the exact submission, service CSV and read-only ML release before delivery."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT, with_duckdb=True):
    root = Path(root)
    rel = json.loads((root / "configs/release.json").read_text(encoding="utf-8"))
    payload = (root / "release/submission.csv").read_bytes()
    assert payload == (root / "service/data/submission.csv").read_bytes(), "service CSV differs"
    assert b"\r" not in payload, "submission must use LF line endings"
    md5 = hashlib.md5(payload).hexdigest()
    assert md5 == rel["scored_forecast"]["forecast_md5"], "submission differs from scored CSV"
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter=";")
    assert reader.fieldnames == ["route", "date", "hour", "prediction"], "invalid columns"
    actual = {}
    for row in reader:
        key = int(row["route"]), row["date"], int(row["hour"])
        value = float(row["prediction"])
        assert key not in actual, "duplicate route/date/hour"
        assert math.isfinite(value) and value >= 0, "invalid prediction"
        actual[key] = value
    dates = [(dt.date(2025,11,1)+dt.timedelta(days=i)).isoformat() for i in range(61)]
    expected = {(route,date,hour) for route in [1,5,7,11,12,17,25,26,28,50] for date in dates for hour in range(24)}
    assert set(actual) == expected, "incomplete or extra grid rows"
    assert all(v == 0 for (r,d,h),v in actual.items() if r == 5 and (d,h) < ("2025-12-16",18)), "route5 before launch"
    assert sum(v for (r,d,h),v in actual.items() if r == 5) > 0, "route5 cold start missing"
    result = {"release_id":rel["release_id"], "model_version":rel["model_version"],
              "rows":len(actual), "md5":md5, "score":rel["scored_forecast"]["score"],
              "CSV_and_service_identical":True, "route5_launch_boundary_valid":True}
    if with_duckdb:
        import duckdb
        con = duckdb.connect(str(root / "release/forecast_release.duckdb"), read_only=True)
        try:
            points = {(r,str(d),h):v for r,d,h,v in con.execute("SELECT route,date,hour,model_prediction FROM forecast_points").fetchall()}
            assert points == actual, "DuckDB forecast differs from scored CSV"
            metadata = con.execute("SELECT release_id,model_version,score,n_points,details FROM release_metadata").fetchall()
            assert len(metadata) == 1
            rid,model,score,n,details = metadata[0]
            assert (rid,model,score,n) == (result["release_id"],result["model_version"],result["score"],len(actual))
            assert json.loads(details)["forecast_md5"] == md5
            result["DuckDB_and_CSV_identical"] = True
        finally:
            con.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-duckdb",action="store_true",help="CSV verification using only Python stdlib")
    parser.add_argument("--output",help="optional JSON verification report")
    args=parser.parse_args()
    result=verify(with_duckdb=not args.no_duckdb)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        Path(args.output).write_text(text+'\n',encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
