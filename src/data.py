"""Target loading: sparse hourly labels -> dense route x date x hour grid.

History = the hackathon label files + any extra label files dropped into data/labels/ (same format:
`route;date;hour;boardings`, e.g. labels_2025_11.csv). The grid runs from the first to the last labelled
date, so adding a month of labels extends the history without touching code.
"""
import pandas as pd

from src import config

KEYS = ["route", "date", "hour"]
EXTRA_LABELS = config.ROOT / "data" / "labels"


def make_grid(start, end, routes=config.ROUTES):
    idx = pd.MultiIndex.from_product(
        [routes, pd.date_range(start, end, freq="D"), range(24)], names=KEYS
    )
    return idx.to_frame(index=False)


def add_calendar_basics(df):
    df = df.copy()
    df["dow"] = df["date"].dt.dayofweek
    return df


def label_files():
    files = [config.LABELS_TRAIN, config.LABELS_TEST]
    if EXTRA_LABELS.exists():
        files += sorted(EXTRA_LABELS.glob("*.csv"))
    return files


def load_history(extra=None):
    """All labelled history on the full grid. Missing label rows inside the range are true zeros.

    extra: optional frame (route, date, hour, boardings), e.g. hourly aggregates from runtime ingest;
    only its (route, date, hour) keys that are not already labelled are added.
    """
    labels = pd.concat([pd.read_csv(p, sep=";", parse_dates=["date"]) for p in label_files()], ignore_index=True)
    dup = labels.duplicated(KEYS)
    if dup.any():
        raise ValueError(f"{dup.sum()} duplicated (route, date, hour) rows across label files")
    if extra is not None and len(extra):
        extra = extra[KEYS + ["boardings"]].copy()
        extra["date"] = pd.to_datetime(extra.date)
        new = extra.merge(labels[KEYS], on=KEYS, how="left", indicator=True)
        labels = pd.concat([labels, new[new._merge == "left_only"].drop(columns="_merge")], ignore_index=True)
    grid = make_grid(labels.date.min(), labels.date.max())
    df = grid.merge(labels, on=KEYS, how="left")
    df["boardings"] = df["boardings"].fillna(0).astype(float)
    return add_calendar_basics(df)
