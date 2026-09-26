"""Ablation of external sources on the 4 temporal folds: base vs base + source.

    python scripts/ablation_external.py        # -> artifacts/ablation_external.csv

Folds (src/validation.py): A Jan–Aug -> Sep–Oct, B Jan–Sep -> Oct, C Jan15–Feb -> Mar–Apr,
D Jan15–Apr -> May–Jun (May holidays). Forecasts use only data before the fold origin.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src import config
from src.data import load_history
from src.models.decomp import decomposition_v2
from src.validation import backtest, weighted_score

FINAL = dict(use_events=True, blend_recent=0.1, regime_by_target=True, daylight_profile=True, daylight_shrink=0.5)
RUNS = [
    ("no external data", "none", dict(use_calendar=False)),
    ("+ production calendar", "calendar", dict()),
    ("+ calendar + school holidays", "calendar+school", dict(use_school=True)),
    ("+ calendar + weather (daily precipitation)", "calendar+weather", dict(use_weather=True)),
    ("final model without daylight", "final-daylight", {**FINAL, "daylight_profile": False}),
    ("final model, daylight strength 0.5 (release)", "final", FINAL),
    ("final model, daylight strength 1.0", "final-daylight1", {**FINAL, "daylight_shrink": 1.0}),
]


def main():
    history = load_history()
    rows = []
    for name, sources, params in RUNS:
        scores, _, _ = backtest(decomposition_v2(**params), history)
        row = {"experiment": name, "sources": sources, "weighted": round(weighted_score(scores), 4),
               **{f"{r.fold}": round(r.wape_score, 4) for r in scores.itertuples()}}
        rows.append(row)
        print(row, flush=True)
    out = config.ARTIFACTS / "ablation_external.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)


if __name__ == "__main__":
    main()
