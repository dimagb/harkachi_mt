"""Regime-aware decomposition: level(route, eff_dow) x hourly share(route, profile group, hour) x calendar.

Everything is estimated from `train` only (strictly before the fold origin).
"""
import numpy as np
import pandas as pd

from src import astro, calendar_ru, events, weather

PROFILE_GROUPS = {
    "dow": lambda s: s,
    "wd_sat_sun": lambda s: np.select([s < 5, s == 5], [0, 5], 6),
}


def flag_anomalies(daily, ratio=1.5, min_share=0.1, window=7):
    """Route-days far from the centred rolling median of the same (route, dow).

    `min_share` guards low-volume days (route 50 weekends): the absolute deviation must also exceed
    that share of the route's median day.
    """
    daily = daily.sort_values("date").copy()
    ok = ~daily.is_special
    ref = (daily[ok].groupby(["route", "dow"]).day
           .transform(lambda s: s.rolling(window, center=True, min_periods=3).median()))
    daily["ref"] = ref.reindex(daily.index)
    scale = daily.groupby("route").day.transform("median")
    r = daily.day / daily.ref.replace(0, np.nan)
    far = (r > ratio) | (r < 1 / ratio)
    big = (daily.day - daily.ref).abs() > min_share * scale
    daily["is_anomaly"] = (far & big).fillna(False) & ok
    return daily


def _daylight(dates):
    """Day length in hours for the given dates (src/astro.py: Open-Meteo for 2025, computed elsewhere)."""
    return astro.daylight_table(dates).daylight_h


def _day_group(dow, mode):
    return (dow >= 5).astype(int) if mode == "wd_we" else np.zeros(len(dow), dtype=int)


def _daylight_adjust(train, prof_days, share, k, target_share, shrink, groups, group):
    """Scale target hourly shares by day length; slopes fitted on the profile days (see decomposition_v2)."""
    h = train.merge(prof_days[["route", "date", "day"]], on=["route", "date"])
    dl = _daylight(pd.concat([h.date, k.date]))
    h = h[h.day > 0]
    base = share.rename("s0").reset_index()
    h["grp"] = group(h.dow)
    h = h.merge(base, on=["route", "grp", "hour"])
    h = h[h.s0 > 0.005]
    h["y"] = h.boardings / h.day / h.s0 - 1
    h["x"] = h.date.map(dl)
    h["g"] = _day_group(h.dow, groups)
    mean_dl = h.groupby("g").x.mean()
    h["xc"] = h.x - h.g.map(mean_dl)
    w = h.s0 * h.day  # expected volume: big routes and hours dominate the slope
    slope = ((w * h.xc * h.y).groupby([h.g, h.hour]).sum() / (w * h.xc ** 2).groupby([h.g, h.hour]).sum())

    g = _day_group(k.dow, groups)
    xt = k.date.map(dl).to_numpy() - pd.Series(g).map(mean_dl).to_numpy()
    b = pd.Series(list(zip(g, k.hour))).map(slope).fillna(0).to_numpy()
    adj = np.clip(1 + shrink * b * xt, 0.5, 1.5)
    s = target_share.to_numpy() * adj
    tot = pd.Series(s).groupby([k.route.to_numpy(), k.date.to_numpy()]).transform("sum").to_numpy()
    return pd.Series(np.where(tot > 0, s / tot, target_share.to_numpy()), index=target_share.index)


def decomposition_v2(level_weeks=4, level_stat="median", regime_match=True, clean=True,
                     profile="dow", profile_scope="school", anomaly_ratio=1.5, working_weekend_mult=0.9,
                     use_calendar=True, use_weather=False, use_school=False, use_events=False,
                     day_mult=None, level_method="median", index_weeks=8, weekend_weeks=None,
                     profile_shrink=1.0, blend_recent=0.0, blend_days=28, blend_clean=False,
                     profile_weeks=None, profile_mix=0.0, holiday_profile="sun",
                     daylight_profile=False, daylight_shrink=1.0, daylight_groups="wd_we", scale=1.0,
                     weather_extreme=False, weather_shrink=5,
                     regime_by_target=False, long_level_weeks=None, horizon_weights=None):
    """use_calendar=False is the ablation: no holiday mapping, holidays are only caught by the anomaly filter.

    use_weather multiplies each day by exp(b * (precip - mean precip)), b fitted on train days only.
    Horizon precipitation is observed weather, i.e. ex-post information for the final forecast.
    use_school: season boundaries from the school calendar, school-holiday days left out of the level.
    use_events: announced route changes get their own level while active; outside them the level
    comes from days without the event (e.g. route 50 weekends return after the repair ends).
    day_mult: {date: multiplier} overriding calendar_ru.DAY_MULT (the release passes estimated factors).
    level_method="weekly": level = route volume over the last `level_weeks` weeks (all weekdays pooled,
        de-seasonalised by a dow index from the last `index_weeks` clean weeks) x that dow index.
    weekend_weeks: longer median window for Sat/Sun levels (fewer observations than weekdays).
    profile_shrink: alpha in alpha*route profile + (1-alpha)*network profile.
    blend_recent: weight of a plain median(route, dow, hour) over the last `blend_days` days (not on event
        route weekends); blend_clean uses only usable (no holiday/anomaly/event) days for that median.
    profile_weeks / profile_mix: hourly profile = mix * (last `profile_weeks` weeks) + (1-mix) * long profile.
    holiday_profile: hourly profile group for official days off ("sun" or "sat"); the level stays Sunday.
    daylight_profile: shift hourly shares with day length (external source #4). For each hour and day group
        (weekday / weekend) a slope of share-ratio on daylight hours is fitted on the profile days, pooled over
        routes; the target day's shares are scaled by 1 + shrink * slope * (daylight - mean daylight) and
        renormalised. Day length is astronomical, so it is known for any future date.
    scale: final global multiplier, set on the test period rather than estimated from the history.
    regime_by_target: summer target days take their level from the last summer weeks seen before the
        cutoff (school target days keep the school-season level). Without summer history the school level
        is used — there is no prior-year information to do better.
    long_level_weeks / horizon_weights: horizon-aware level. level = w(h) * recent level + (1 - w(h)) *
        level over the last `long_level_weeks` weeks of the same regime, where horizon_weights is a list of
        (max_horizon_days, w) pairs checked in order; the last w applies beyond them.
    """
    group = PROFILE_GROUPS[profile]
    weather_daily = weather.load_daily() if use_weather else None

    def annotate(df, as_of):
        df = calendar_ru.annotate(df, use_school=use_school)
        if not use_calendar:
            df["eff_dow"] = df.dow
            df[["is_special", "is_working_weekend"]] = False
        df["event"] = events.active(df, as_of) if use_events else False
        return df

    def predict(train, keys):
        as_of = train.date.max() + pd.Timedelta(days=1)
        daily = train.groupby(["route", "date", "dow"], as_index=False).boardings.sum()
        daily = flag_anomalies(annotate(daily.rename(columns={"boardings": "day"}), as_of), ratio=anomaly_ratio)
        usable = ~daily.is_special
        if clean:
            usable &= ~daily.is_anomaly

        # ---- level: last `level_weeks` weeks of usable (optionally school-season) days
        lvl_src = daily[usable & daily.school_season] if regime_match else daily[usable]
        if use_school:
            lvl_src = lvl_src[~lvl_src.is_school_holiday]
        cutoff = lvl_src.date.max() - pd.Timedelta(weeks=level_weeks)
        by = ["route", "dow"]
        normal = lvl_src[~lvl_src.event]
        recent = normal[normal.date > cutoff]
        level = recent.groupby(by).day.agg(level_stat)
        fallback = lvl_src.groupby(by).day.median()
        # event-affected groups fall back to their last clean pre-event weeks, not the all-history median
        event_groups = lvl_src[lvl_src.event].set_index(by).index.unique()
        last_n = normal.sort_values("date").groupby(by).tail(level_weeks).groupby(by).day.agg(level_stat)
        fallback.loc[fallback.index.intersection(event_groups)] = last_n.reindex(event_groups).dropna()
        level = level.combine_first(fallback).rename("level").rename_axis(["route", "eff_dow"])
        if weekend_weeks:
            we = normal[(normal.dow >= 5) & (normal.date > lvl_src.date.max() - pd.Timedelta(weeks=weekend_weeks))]
            level.update(we.groupby(by).day.agg(level_stat).rename_axis(["route", "eff_dow"]))
        if level_method == "weekly":
            idx_src = normal[normal.date > lvl_src.date.max() - pd.Timedelta(weeks=index_weeks)].copy()
            idx_src["wk"] = idx_src.date.dt.to_period("W")
            wk_n = idx_src.groupby(["route", "wk"]).day.transform("size")
            idx_src = idx_src[wk_n >= 5]
            idx_src["rel"] = idx_src.day / idx_src.groupby(["route", "wk"]).day.transform("mean")
            index = idx_src.groupby(by).rel.median()
            index = index / index.groupby(level=0).transform("mean")
            rec = recent.join(index.rename("idx"), on=by)
            rec = rec[rec.idx > 0.05]  # near-zero dows (closed routes) carry no level information
            base_lvl = (rec.day / rec.idx).groupby(rec.route).median()
            weekly = (index * base_lvl.reindex(index.index.get_level_values(0)).to_numpy())
            level.update(weekly.rename_axis(["route", "eff_dow"]).dropna())
        in_event = lvl_src[lvl_src.event & (lvl_src.date > cutoff)]
        event_level = in_event.groupby(by).day.agg(level_stat).rename("event_level").rename_axis(["route", "eff_dow"])

        # ---- horizon-aware blend: a longer window of the same regime for far-away days
        level_long = None
        if long_level_weeks and horizon_weights:
            long_cut = lvl_src.date.max() - pd.Timedelta(weeks=long_level_weeks)
            level_long = normal[normal.date > long_cut].groupby(by).day.agg(level_stat)
            level_long = level_long.rename("level_long").rename_axis(["route", "eff_dow"])
        # ---- summer targets: level from the last summer weeks, if any were observed
        summer_level = None
        if regime_by_target:
            s_src = daily[usable & daily.is_summer & ~daily.event]
            if len(s_src):
                s_cut = s_src.date.max() - pd.Timedelta(weeks=level_weeks)
                summer_level = (s_src[s_src.date > s_cut].groupby(by).day.agg(level_stat)
                                .rename("summer_level").rename_axis(["route", "eff_dow"]))

        # ---- hourly profile: median share of the day
        prof_days = daily[usable & (daily.school_season if profile_scope == "school" else True)]

        def profile_from(days):
            hourly = train.merge(days[["route", "date", "day"]], on=["route", "date"])
            hourly = hourly[hourly.day > 0]
            hourly["grp"] = group(hourly.dow)
            s = (hourly.boardings / hourly.day).groupby([hourly.route, hourly.grp, hourly.hour]).median()
            s = s / s.groupby(level=[0, 1]).transform("sum")
            s.index.names = ["route", "grp", "hour"]
            return s

        share = profile_from(prof_days)
        if profile_weeks and profile_mix > 0:
            rec_days = prof_days[prof_days.date > prof_days.date.max() - pd.Timedelta(weeks=profile_weeks)]
            rec_share = profile_from(rec_days).reindex(share.index)
            share = (profile_mix * rec_share + (1 - profile_mix) * share).fillna(share)
            share = share / share.groupby(level=[0, 1]).transform("sum")
        if profile_shrink < 1:
            net = share.groupby(level=["grp", "hour"]).median()
            net_b = net.reindex(share.index.droplevel("route")).to_numpy()
            share = profile_shrink * share + (1 - profile_shrink) * net_b
            share = share / share.groupby(level=[0, 1]).transform("sum")
        share = share.rename("share")

        k = annotate(keys, as_of)
        k["grp"] = group(k.eff_dow)
        if holiday_profile == "sat":
            k.loc[k.is_day_off | k.is_block_weekend, "grp"] = np.asarray(group(pd.Series([5])))[0]
        out = k.join(level, on=["route", "eff_dow"]).join(share, on=["route", "grp", "hour"])
        if level_long is not None:
            h = (k.date - as_of).dt.days.to_numpy() + 1
            w = np.select([h <= b for b, _ in horizon_weights], [wt for _, wt in horizon_weights],
                          horizon_weights[-1][1])
            ll = k.join(level_long, on=["route", "eff_dow"]).level_long.to_numpy()
            out["level"] = np.where(np.isnan(ll), out.level, w * out.level + (1 - w) * ll)
        if summer_level is not None:
            sl = k.join(summer_level, on=["route", "eff_dow"]).summer_level
            out["level"] = np.where(k.is_summer & sl.notna(), sl, out.level)
        out = out.join(event_level, on=["route", "eff_dow"])
        out["level"] = np.where(k.event & out.event_level.notna(), out.event_level, out.level)
        mult = np.where(k.is_working_weekend, working_weekend_mult, 1.0)
        if use_calendar:
            dm = k.day_mult if day_mult is None else k.date.map(day_mult).fillna(1.0)
            mult = mult * dm.to_numpy()
        if weather_extreme:
            wd = weather.load_daily_full()
            factors = weather.extreme_factors(daily, wd, shrink=weather_shrink)
            cond = k.date.map(weather.classify(wd)).fillna("normal")
            f = [factors.get((c, we), 1.0) for c, we in zip(cond, k.dow >= 5)]
            mult = mult * np.asarray(f)
        if use_weather:
            slope, _ = weather.fit_precip_slope(daily, weather_daily)
            # the level already carries the weather of its own window, so centre on that window
            mean_precip = weather_daily.precip.reindex(recent.date.unique()).mean()
            precip = k.date.map(weather_daily.precip).fillna(mean_precip).to_numpy()
            mult = mult * np.exp(slope * (precip - mean_precip))
        if daylight_profile:
            out["share"] = _daylight_adjust(train, prof_days, share, k, out.share, daylight_shrink,
                                            daylight_groups, group)
        pred = (out.level * out.share * mult).fillna(0).to_numpy()
        if blend_recent > 0:
            last = train[train.date > train.date.max() - pd.Timedelta(days=blend_days)]
            if blend_clean:
                ok = daily.loc[usable & ~daily.event, ["route", "date"]]
                last = last.merge(ok, on=["route", "date"])
            med = last.groupby(["route", "dow", "hour"]).boardings.median().rename("med")
            med.index.names = ["route", "eff_dow", "hour"]
            m = k.join(med, on=["route", "eff_dow", "hour"]).med.fillna(0).to_numpy() * mult
            event_routes = events.regime_routes(as_of - pd.Timedelta(days=1)) if use_events else []
            skip = (k.route.isin(event_routes) & (k.dow >= 5)).to_numpy()
            pred = np.where(skip, pred, (1 - blend_recent) * pred + blend_recent * m)
        return pred * scale

    return predict
