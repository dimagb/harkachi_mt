"""Calendar sources: Russian production calendar (#1) and Moscow school holidays (#2), for any covered year.

#1 data/external/production_calendar.csv — official non-working days and transfers, `source` per row:
   2025: Постановление Правительства РФ № 1335 от 04.10.2024 (4 Jan -> 2 May, 5 Jan -> 31 Dec,
         23 Feb -> 8 May, 8 Mar -> 13 Jun, 1 Nov (Sat) -> 3 Nov);
   2026: Постановление Правительства РФ № 1466 от 24.09.2025 (3 Jan -> 9 Jan, 4 Jan -> 31 Dec) plus
         Labour Code art. 112 (8 Mar -> 9 Mar, 9 May -> 11 May).
   To extend to a new year, append its rows; nothing else in the code is year-specific.
#2 data/external/school_holidays_moscow.csv — Moscow school holidays, source URL per row. Rows named
   summer_YYYY define the school summer.

Recurring rules (any year): New-Year period = 1–12 January; calendar summer = June–August;
pre-New-Year week = 27–30 December.

Empirical rule checked on Jan/May/Jun 2025: an official day off on a weekday carries Sunday-level
traffic (ratio to Sunday ~0.8–1.1), a weekend inside a holiday block also looks like a Sunday,
shortened pre-holiday days look like ordinary weekdays.
"""
import pandas as pd

from src import config

YEARS = range(2024, 2031)  # recurring rules are materialised for these years

_cal = pd.read_csv(config.EXTERNAL / "production_calendar.csv", parse_dates=["date"])
DAYS_OFF_ON_WEEKDAYS = pd.DatetimeIndex(_cal.date[_cal.day_type == "day_off"])
HOLIDAY_BLOCK_WEEKENDS = pd.DatetimeIndex(_cal.date[_cal.day_type == "block_weekend"])
WORKING_WEEKENDS = pd.DatetimeIndex(_cal.date[_cal.day_type == "working_weekend"])
CALENDAR_COVERAGE = (_cal.date.min().year, _cal.date.max().year)

_school = pd.read_csv(config.EXTERNAL / "school_holidays_moscow.csv", parse_dates=["start", "end"])
SCHOOL_HOLIDAYS = pd.DatetimeIndex(sorted(set().union(
    *[pd.date_range(r.start, r.end) for r in _school.itertuples()])))
SCHOOL_SUMMER = pd.DatetimeIndex(sorted(set().union(
    *[pd.date_range(r.start, r.end) for r in _school[_school.name.str.startswith("summer")].itertuples()])))

# New Year holidays have their own, much deeper pattern (1 Jan ~0.45 of a Sunday); keep them out of stats.
NEW_YEAR_PERIOD = pd.DatetimeIndex(sorted(set().union(*[pd.date_range(f"{y}-01-01", f"{y}-01-12") for y in YEARS])))
SUMMER = pd.DatetimeIndex(sorted(set().union(*[pd.date_range(f"{y}-06-01", f"{y}-08-31") for y in YEARS])))
PRE_NEW_YEAR = pd.DatetimeIndex(sorted(set().union(*[pd.date_range(f"{y}-12-27", f"{y}-12-30") for y in YEARS])))

SUNDAY, FRIDAY = 6, 4

# Pre-New-Year days: no analog inside a single year of history, so these are assumptions. Scale taken
# from the closest analog in the data: working days right after the January holidays (9–10 Jan 2025 ran
# at 0.87–0.89 of a normal weekday, the following weekend at 0.86–0.93). The release passes the values
# estimated by src/factors.py instead (see day_mult_from_factors).
PRE_NEW_YEAR_WEEKDAY, PRE_NEW_YEAR_WEEKEND = 0.88, 0.93
DAY_MULT = {d: (PRE_NEW_YEAR_WEEKEND if d.dayofweek >= 5 else PRE_NEW_YEAR_WEEKDAY) for d in PRE_NEW_YEAR}


def day_mult_from_factors(factors):
    """{date: multiplier} from the estimated seasonality factors:
    pre-New-Year days (27–30 Dec) and, when estimated, 1 January and the other New-Year days off
    (relative to the Sunday level the model already assigns to days off)."""
    ny = factors["seasonality"]
    mult = {d: ny["new_year_week_weekend" if d.dayofweek >= 5 else "new_year_week_weekday"]["value"]
            for d in PRE_NEW_YEAR}
    off = DAYS_OFF_ON_WEEKDAYS.union(HOLIDAY_BLOCK_WEEKENDS)
    if "new_year_day" in ny:
        for d in NEW_YEAR_PERIOD:
            if d.month == 1 and d.day == 1:
                mult[d] = ny["new_year_day"]["value"]
            elif d in off:
                mult[d] = ny["new_year_holidays"]["value"]
    # the first two working days after the New-Year holidays: that is exactly what new_year_week_weekday
    # measures (9–10 Jan 2025); only for years the production calendar covers
    for y in range(CALENDAR_COVERAGE[0], CALENDAR_COVERAGE[1] + 1):
        jan = pd.date_range(f"{y}-01-02", f"{y}-01-20")
        working = [d for d in jan if d.dayofweek < 5 and d not in off]
        for d in working[:2]:
            mult[d] = ny["new_year_week_weekday"]["value"]
    return mult


def check_coverage(dates):
    """Raise if forecast dates fall outside the production calendar (holidays would be silently missed)."""
    years = set(pd.DatetimeIndex(dates).year)
    missing = sorted(y for y in years if not CALENDAR_COVERAGE[0] <= y <= CALENDAR_COVERAGE[1])
    if missing:
        raise ValueError(f"production_calendar.csv has no rows for {missing}; add that year first")


def annotate(df, use_school=False):
    """Adds day-level calendar columns to any frame with `date` and `dow`.

    use_school: define the season by the school calendar (school summer) and flag school holidays.
    """
    df = df.copy()
    d = df["date"]
    df["is_day_off"] = d.isin(DAYS_OFF_ON_WEEKDAYS)
    df["is_block_weekend"] = d.isin(HOLIDAY_BLOCK_WEEKENDS)
    df["is_working_weekend"] = d.isin(WORKING_WEEKENDS)
    df["is_special"] = df.is_day_off | df.is_block_weekend | df.is_working_weekend | d.isin(NEW_YEAR_PERIOD)
    df["is_school_holiday"] = d.isin(SCHOOL_HOLIDAYS) & ~d.isin(SCHOOL_SUMMER)
    summer = SCHOOL_SUMMER if use_school else SUMMER
    df["school_season"] = ~d.isin(summer) & ~d.isin(NEW_YEAR_PERIOD)
    df["is_summer"] = d.isin(summer)
    # Day type used to look up level and hourly profile.
    df["eff_dow"] = df["dow"]
    df.loc[df.is_day_off | df.is_block_weekend, "eff_dow"] = SUNDAY
    df.loc[df.is_working_weekend, "eff_dow"] = FRIDAY
    df["day_mult"] = d.map(DAY_MULT).fillna(1.0)
    return df
