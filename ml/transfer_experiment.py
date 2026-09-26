"""Secondary network effects: does demand move to other tram routes when a route is closed or shortened?

    python -m ml.transfer_experiment        # writes artifacts/transfer_experiment.{csv,md}

For every affected day and every other observed route j:  effect_j(day) = actual_j / expected_j, then divided
by the median effect of the other (unconfounded) routes on the same day (network control: removes season,
weather and holiday shocks shared by the whole network).
The rule effect_j = median over affected days is published only if
  - there are at least MIN_DAYS affected days,
  - the sign is stable (>= SIGN_SHARE of days on the same side of 1),
  - |median - 1| exceeds NOISE_MULT x the spread of the same statistic on placebo days without the event,
  - a placebo test (medians of random same-size sets of no-event days) gives p < MAX_P,
  - the target is not flagged as confounded (a known simultaneous change on that route).
Otherwise no secondary coefficient is produced.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src import calendar_ru, config
from src.data import load_history
from src.models.decomp import flag_anomalies

MIN_DAYS = 4
SIGN_SHARE = 0.8
NOISE_MULT = 2.0
MAX_P = 0.05          # placebo test (random sets of no-event days), required in addition to the rules above
PLACEBO_DRAWS = 20000

OBSERVED_ROUTES = [1, 7, 11, 12, 17, 25, 26, 28, 50]


@dataclass
class Disruption:
    name: str
    event_type: str
    source_route: int
    start: str
    end: str
    weekends_only: bool
    method: str                    # "week_ratio" (weekend events) or "same_dow" (all-day events)
    baseline: list                 # [(start, end), ...] windows for expected values / placebo days
    source: str
    confounded: dict = field(default_factory=dict)   # target route -> reason
    exclude_targets: tuple = ()
    dates: tuple = ()              # explicit affected days (otherwise every day in [start, end] matching the filter)


DISRUPTIONS = [
    Disruption(
        name="A: маршрут 50 не ходит по выходным (ремонт в Протопоповском переулке)",
        event_type="FULL_CLOSURE", source_route=50, start="2025-09-06", end="2025-10-31", weekends_only=True,
        method="week_ratio", baseline=[("2025-02-01", "2025-05-31")],
        source="https://newsvostok.ru/dlya-tramvaev-7-i-50-izmeneniya-po-vyhodnym-budut-dejstvovat-do-kontsa-oseni/",
        exclude_targets=(7,),  # route 7 is itself shortened on the same weekends
    ),
    Disruption(
        name="B: изменение участка маршрута 7 Красносельская — Белорусский вокзал",
        event_type="SHORTENING", source_route=7, start="2025-07-10", end="2025-08-10", weekends_only=False,
        method="same_dow", baseline=[("2025-06-16", "2025-07-06"), ("2025-08-14", "2025-08-31")],
        source="data: route 7 at ~40% of its level on weekdays 10.07–10.08.2025",
        confounded={50: "маршруты 50 и 13 объединены на время ремонта (июль 2025, uv-kurier.ru/2025/07/08): "
                        "рост 50 нельзя отделить от удлинения самого маршрута"},
    ),
    Disruption(
        name="C: маршрут 17 не работал в выходные апреля (1–13% обычного объёма)",
        event_type="FULL_CLOSURE", source_route=17, start="2025-04-12", end="2025-04-27", weekends_only=True,
        method="week_ratio", baseline=[("2025-02-01", "2025-03-29")],
        source="data: route 17 carried 1–13% of its usual weekend volume on 12–13 and 26–27.04.2025",
        # 5–6 April are left out: the same weekend routes 1/11/12/50 ran with 20–40% fewer vehicles
        # (network change of 31.03–06.04), so any shift there cannot be attributed to route 17
        dates=("2025-04-12", "2025-04-13", "2025-04-26", "2025-04-27"),
    ),
]


def daily_table():
    h = load_history()
    d = h.groupby(["route", "date", "dow"], as_index=False).boardings.sum().rename(columns={"boardings": "day"})
    d = flag_anomalies(calendar_ru.annotate(d))
    d["clean"] = ~d.is_special & ~d.is_anomaly
    return d[d.route.isin(OBSERVED_ROUTES)]


def _in(dates, windows):
    m = pd.Series(False, index=dates.index)
    for a, b in windows:
        m |= dates.between(a, b)
    return m


def _week_ratio_effects(d, ev, target):
    """weekend day / mean of the same week's weekdays, relative to the usual ratio on baseline weeks."""
    t = d[d.route == target].copy()
    t["week"] = t.date.dt.to_period("W")
    wd = t[(t.dow < 5) & t.clean].groupby("week").day.mean().rename("wd_mean")
    t = t.join(wd, on="week")
    t["r"] = t.day / t.wd_mean
    base = t[_in(t.date, ev.baseline) & t.clean & (t.dow >= 5)]
    usual = base.groupby("dow").r.median()
    t["effect"] = t.r / t.dow.map(usual)
    affected = t[t.date.between(ev.start, ev.end) & (t.dow >= 5) & ~t.is_special]
    if ev.dates:
        affected = affected[affected.date.isin(pd.to_datetime(list(ev.dates)))]
    placebo = base.assign(effect=base.r / base.dow.map(usual))
    return affected.set_index("date").effect.dropna(), placebo.set_index("date").effect.dropna()


def _same_dow_effects(d, ev, target):
    """day / median of the same weekday on baseline days (leave-one-out for placebo days)."""
    t = d[d.route == target]
    base = t[_in(t.date, ev.baseline) & t.clean]
    expected = base.groupby("dow").day.median()
    days = t[t.date.between(ev.start, ev.end) & ~t.is_special]
    if ev.weekends_only:
        days = days[days.dow >= 5]
    if ev.dates:
        days = days[days.date.isin(pd.to_datetime(list(ev.dates)))]
    effect = pd.Series((days.day / days.dow.map(expected)).to_numpy(), index=days.date)
    placebo = {}
    for i, row in base.iterrows():
        others = base.drop(index=i)
        ref = others[others.dow == row.dow].day.median()
        placebo[row.date] = row.day / ref if ref else np.nan
    return effect.dropna(), pd.Series(placebo).dropna()


def run():
    d = daily_table()
    rows = []
    for ev in DISRUPTIONS:
        fn = _week_ratio_effects if ev.method == "week_ratio" else _same_dow_effects
        targets = [t for t in OBSERVED_ROUTES if t != ev.source_route and t not in ev.exclude_targets]
        per_route = {t: fn(d, ev, t) for t in targets}
        eff_all = pd.DataFrame({t: e for t, (e, _) in per_route.items()})
        plc_all = pd.DataFrame({t: p for t, (_, p) in per_route.items()})
        for target in targets:
            # network control: divide by the median effect of the other targets on the same day, which removes
            # shocks common to the whole network (season, weather, holidays) — a difference-in-differences
            others = [t for t in targets if t != target and t not in ev.confounded]
            eff = (eff_all[target] / eff_all[others].median(axis=1)).dropna()
            placebo = (plc_all[target] / plc_all[others].median(axis=1)).dropna()
            raw = eff_all[target].dropna()
            if eff.empty or placebo.empty:
                continue
            med = float(eff.median())
            noise = float((placebo - 1).abs().median() * 1.4826)  # robust sd of the no-event statistic
            sign_share = float(max((eff > 1).mean(), (eff < 1).mean()))
            # placebo test: how often a random set of the same number of no-event days has a median
            # at least as far from 1 (two-sided); an extra requirement on top of the fixed rule
            rng = np.random.default_rng(0)
            pool = placebo.to_numpy()
            if len(pool) >= len(eff):  # sets without repetition: random permutation per row, first n days
                idx = np.argsort(rng.random((PLACEBO_DRAWS, len(pool))), axis=1)[:, :len(eff)]
                draws = pool[idx]
            else:
                draws = rng.choice(pool, size=(PLACEBO_DRAWS, len(eff)), replace=True)
            p_value = float((np.abs(np.median(draws, axis=1) - 1) >= abs(med - 1)).mean())
            reasons = []
            if len(eff) < MIN_DAYS:
                reasons.append(f"мало дней ({len(eff)})")
            if sign_share < SIGN_SHARE:
                reasons.append(f"знак неустойчив ({sign_share:.0%})")
            if abs(med - 1) <= NOISE_MULT * noise:
                reasons.append(f"|эффект−1|={abs(med - 1):.3f} ≤ {NOISE_MULT}×шум ({noise:.3f})")
            if p_value >= MAX_P:
                reasons.append(f"placebo p={p_value:.3f}")
            if target in ev.confounded:
                reasons.append("смешивающий фактор: " + ev.confounded[target])
            rows.append({"disruption": ev.name, "event_type": ev.event_type, "source_route": ev.source_route,
                         "target_route": target, "n_days": len(eff), "raw_effect": round(float(raw.median()), 4),
                         "effect_median": round(med, 4),
                         "sign_share": round(sign_share, 3), "noise_sd": round(noise, 4),
                         "placebo_p": round(p_value, 4),
                         "published": not reasons, "reason": "; ".join(reasons) or "устойчивый эффект",
                         "source": ev.source})
    return pd.DataFrame(rows)


def impact_rules(results):
    """network_impact_rules rows: only published effects."""
    pub = results[results.published]
    return pd.DataFrame({"event_type": pub.event_type, "source_route": pub.source_route,
                         "target_route": pub.target_route, "factor": pub.effect_median,
                         "source": "historical_estimate: " + pub.disruption})


def main():
    res = run()
    out = config.ARTIFACTS
    out.mkdir(parents=True, exist_ok=True)
    res.to_csv(out / "transfer_experiment.csv", index=False)
    lines = ["# Перетекание спроса при закрытиях и изменениях маршрутов", "",
             f"Правило публикации: ≥ {MIN_DAYS} дней, устойчивый знак ≥ {SIGN_SHARE:.0%}, "
             f"|эффект − 1| > {NOISE_MULT} × шум на днях без события, placebo p < {MAX_P}, "
             "нет смешивающего фактора. Эффект — медиана по дням отношения факт / ожидание, делённого на "
             "медианное такое же отношение остальных маршрутов в тот же день (контроль по сети).", ""]
    for name, g in res.groupby("disruption", sort=False):
        lines += [f"## {name}", "",
                  "| маршрут | дней | сырой эффект | с контролем по сети | знак | шум | placebo p | опубликован | причина |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r.target_route} | {r.n_days} | {r.raw_effect:.3f} | {r.effect_median:.3f} | {r.sign_share:.0%} | "
                  f"{r.noise_sd:.3f} | {r.placebo_p:.4f} | {'да' if r.published else 'нет'} | {r.reason} |"
                  for r in g.itertuples()]
        lines.append("")
    if not res.published.any():
        lines.append("В доступных исторических данных статистически устойчивое перетекание на наблюдаемые "
                     "трамвайные маршруты не обнаружено, поэтому искусственные secondary coefficients не применяются.")
    (out / "transfer_experiment.md").write_text("\n".join(lines), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(res.drop(columns=["source", "disruption"]).to_string(index=False))
    return res


if __name__ == "__main__":
    main()
