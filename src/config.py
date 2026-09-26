"""Paths and constants. Data locations can be overridden (container: `python -m ml.build_release --data /data`):

    TRAM_DATASET   folder with labels/labels_day_train.csv, labels/labels_day_test.csv
    TRAM_EXTERNAL  folder with external sources (production_calendar.csv, network_events.csv, ...)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = Path(os.environ.get("TRAM_DATASET", ROOT / "dataset"))
LABELS_TRAIN = DATASET / "labels" / "labels_day_train.csv"
LABELS_TEST = DATASET / "labels" / "labels_day_test.csv"

EXTERNAL = Path(os.environ.get("TRAM_EXTERNAL", ROOT / "data" / "external"))
ARTIFACTS = ROOT / "artifacts"

ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]
HISTORY_START = "2025-01-01"
HISTORY_END = "2025-10-31"
FORECAST_START = "2025-11-01"
FORECAST_END = "2025-12-31"
