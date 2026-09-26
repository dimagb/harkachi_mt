"""Versioned network state (external source #5/#6): data/external/network_events.csv.

Each row is a route change with two kinds of dates:
  published_at            when the change became public — an event is visible to a forecast made at
                          `cutoff` only if published_at <= cutoff (no ex-post leakage in backtests);
  valid_from / valid_to   when the change is in effect (valid_to empty = open-ended).
day_type (all / weekday / weekend) and start_hour..end_hour restrict it further.

effect_type:
  observed_regime  the level while the event is active is taken from the days already observed under it,
                   and outside the window the level comes from days without it (decomposition_v2);
  new_route        cold-start of a route without history (src/models/cold_start.py);
  multiplier       prediction x effect_value while active;
  closure          prediction x 0 while active.
`key` is the stable identifier used in forecast_context.csv / correction_factors.json.
"""
import numpy as np
import pandas as pd

from src import config

EVENTS = pd.read_csv(config.EXTERNAL / "network_events.csv",
                     parse_dates=["published_at", "valid_from", "valid_to"])


def known(cutoff):
    """Events published on or before the cutoff date (all of them if cutoff is None)."""
    if cutoff is None:
        return EVENTS
    return EVENTS[EVENTS.published_at <= pd.Timestamp(cutoff)]


def _mask(df, e):
    """Rows of df (route, date, dow[, hour]) covered by event e."""
    start = e.valid_from
    end = e.valid_to if pd.notna(e.valid_to) else pd.Timestamp.max
    if "hour" in df:
        stamp = df.date + pd.to_timedelta(df.hour, unit="h")
        in_time = (stamp >= start.floor("h")) & (stamp <= end) & df.hour.between(e.start_hour, e.end_hour)
    else:
        in_time = df.date.between(start.normalize(), end.normalize())
    days = {"weekend": df.dow >= 5, "weekday": df.dow < 5}.get(e.day_type, pd.Series(True, index=df.index))
    return ((df.route == e.route) & in_time & days).to_numpy()


def active(df, as_of, effect_types=("observed_regime",)):
    """Bool array: row is inside an event of the given effect types published before `as_of`
    (as_of = cutoff + 1 day, i.e. the first forecast day)."""
    flag = np.zeros(len(df), dtype=bool)
    for e in known(pd.Timestamp(as_of) - pd.Timedelta(days=1)).itertuples():
        if e.effect_type in effect_types:
            flag |= _mask(df, e)
    return flag


def regime_routes(cutoff=None):
    ev = known(cutoff)
    return ev.loc[ev.effect_type == "observed_regime", "route"].unique()


def label(df, cutoff, effect_types=None, regime_until=None):
    """Event key per row (the first matching known event) or 'none'.

    effect_types: only these effect types (all if None).
    regime_until: treat observed_regime events as lasting until this date (legacy forecasts that carried
    the regime through the horizon).
    """
    out = np.full(len(df), "none", dtype=object)
    for e in known(cutoff).itertuples():
        if effect_types is not None and e.effect_type not in effect_types:
            continue
        if regime_until is not None and e.effect_type == "observed_regime":
            e = e._replace(valid_to=pd.Timestamp(regime_until))
        m = _mask(df, e) & (out == "none")
        out[m] = e.key
    return out


def get_network_state(route, date, hour, cutoff):
    """Known events affecting (route, date, hour) for a forecast made at `cutoff`."""
    probe = pd.DataFrame({"route": [route], "date": [pd.Timestamp(date).normalize()],
                          "dow": [pd.Timestamp(date).dayofweek], "hour": [hour]})
    return [e._asdict() for e in known(cutoff).itertuples() if _mask(probe, e)[0]]


def apply_multipliers(keys, pred, cutoff):
    """'multiplier' and 'closure' events known at the cutoff."""
    pred = np.asarray(pred, float).copy()
    for e in known(cutoff).itertuples():
        if e.effect_type == "closure":
            pred[_mask(keys, e)] = 0.0
        elif e.effect_type == "multiplier":
            pred[_mask(keys, e)] *= float(e.effect_value)
    return pred
