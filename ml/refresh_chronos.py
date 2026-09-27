"""Run pinned foundation inference and refresh guarded component snapshots.

python -m ml.refresh_chronos --data service/data --mode leaderboard
"""
import argparse
from ml.build_release import configure_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="service/data")
    parser.add_argument("--mode", choices=["production", "leaderboard"], default="leaderboard")
    parser.add_argument("--model-path", help="local directory of the pinned pretrained revision")
    args = parser.parse_args()
    configure_paths(args.data)
    import pandas as pd
    from src import events
    from src.data import load_history
    from src.models.chronos_ensemble import infer, export_snapshot, load_pipeline
    history = load_history()
    cutoff, end = pd.Timestamp("2025-10-31"), pd.Timestamp("2025-12-31")
    pipe = load_pipeline(args.model_path)
    with events.information_set(cutoff if args.mode == "production" else None):
        daily, hourly = infer(history, cutoff, end, pipe)
    export_snapshot(history, cutoff, end, args.mode, daily, hourly)
    print("Chronos components saved; rebuild and verify the submission md5 before assigning a score.")


if __name__ == "__main__":
    main()
