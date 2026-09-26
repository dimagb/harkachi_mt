"""Cold start of routes that have no (or little) history: `new_route` events in network_events.csv.

Fallback hierarchy for the level of a new route:
  1. its own observations after launch (if the history reaches past valid_from), shrunk to the prior;
  2. prior = effect_value x forecast of `template_route` (a similar existing route);
Predecessor routes, overlap and transfer graphs would slot in between 1 and 2 when that data exists;
today only the template prior is available.

Own observations take over as they accumulate: weight = n_days / (n_days + OBS_SHRINK_DAYS).
"""
import numpy as np
import pandas as pd

from src import events

OBS_SHRINK_DAYS = 7


def predict_new_routes(keys, pred, history=None, cutoff=None, ratio_override=None):
    """Overwrite predictions of new routes known at `cutoff` (all events if cutoff is None)."""
    pred = np.asarray(pred, float).copy()
    base = pd.Series(pred, index=pd.MultiIndex.from_frame(keys[["route", "date", "hour"]]))
    stamp = keys.date + pd.to_timedelta(keys.hour, unit="h")
    for e in events.known(cutoff).itertuples():
        if e.effect_type != "new_route":
            continue
        on = ((keys.route == e.route) & (stamp >= e.valid_from)).to_numpy()
        if not on.any():
            continue
        ratio = (ratio_override or {}).get(e.route, float(e.effect_value))
        tmpl = base.reindex(pd.MultiIndex.from_arrays(
            [np.full(on.sum(), e.template_route), keys.date[on], keys.hour[on]])).to_numpy()
        prior = ratio * np.nan_to_num(tmpl)
        pred[on] = prior * _observed_adjustment(e, ratio, history)
    return pred


def _observed_adjustment(e, ratio, history):
    """Shrunk ratio of observed boardings to the prior over the days since launch (1.0 without data)."""
    if history is None:
        return 1.0
    since = history[history.date >= e.valid_from.normalize()]
    own = since[since.route == e.route].groupby("date").boardings.sum()
    tmpl = since[since.route == e.template_route].groupby("date").boardings.sum()
    days = own.index.intersection(tmpl.index)
    days = days[days > e.valid_from.normalize()]  # the launch day is partial
    if len(days) == 0 or tmpl[days].sum() <= 0:
        return 1.0
    observed = own[days].sum() / (ratio * tmpl[days].sum())
    w = len(days) / (len(days) + OBS_SHRINK_DAYS)
    return (1 - w) + w * observed
