"""Rolling-origin evaluation of the final model (production mode: only information known at each cutoff).

    python scripts/rolling_backtest.py            # all variants below
    python scripts/rolling_backtest.py final      # a subset

Cutoffs: month ends Feb–Sep 2025; horizon buckets 1–7 / 8–14 / 15–30 / 31–60 days.
Outputs artifacts/rolling/<variant>/{summary,by_origin,slices}.csv and artifacts/rolling/comparison.csv.
Acceptance rule for a model feature: overall pooled score better, 31–60 bucket not worse,
and no cutoff worse by more than 0.005.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src import config
from src.data import load_history
from src.pipeline import ForecastConfig
from src.rolling import evaluate_origins

FINAL = ForecastConfig.from_files(mode="production").model_params


def _with_params(**params):
    cfg = ForecastConfig.from_files(mode="production")
    cfg.model_params = {**FINAL, **params}
    return cfg


VARIANTS = {
    "final": _with_params(),
    "without_target_regime": _with_params(regime_by_target=False),        # accepted feature, ablated
    "horizon_blend_12w": _with_params(long_level_weeks=12,                 # rejected: gain within noise
                                      horizon_weights=[(14, 1.0), (30, 0.7), (60, 0.5)]),
}


def run(names):
    history = load_history()
    out_root = config.ARTIFACTS / "rolling"
    rows = []
    for name in names:
        res = evaluate_origins(history, VARIANTS[name])
        out = out_root / name
        out.mkdir(parents=True, exist_ok=True)
        res.summary.to_csv(out / "summary.csv", index=False)
        res.by_origin.to_csv(out / "by_origin.csv", index=False)
        res.slices.to_csv(out / "slices.csv", index=False)
        per_origin = res.by_origin[res.by_origin.bucket == "all"].set_index("origin").wape_score
        rows.append({"variant": name, **{k: round(v, 4) for k, v in res.headline().items()},
                     **{f"o_{o.strftime('%m%d')}": round(v, 4) for o, v in per_origin.items()}})
        print(rows[-1], flush=True)
    comp = pd.DataFrame(rows)
    comp.to_csv(out_root / "comparison.csv", index=False)
    return comp


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    print(run(sys.argv[1:] or list(VARIANTS)).to_string(index=False))
