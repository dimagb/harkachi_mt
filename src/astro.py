"""Sunrise, sunset and day length for Moscow on any date (NOAA solar position algorithm).

Day length is known in advance for any future date, so it is a KNOWN_FUTURE feature. The Open-Meteo file
(data/external/daylight_moscow_2025.csv) is kept for 2025 so existing forecasts stay byte-identical;
other dates are computed here. The two agree within a few minutes (see tests/test_pipeline.py).
"""
import numpy as np
import pandas as pd

from src import config

LAT, LON, UTC_OFFSET = 55.75, 37.62, 3.0  # Moscow, UTC+3 all year
ZENITH = 90.833  # sunrise/sunset: geometric horizon + refraction + solar radius


def sun_times(dates):
    """DataFrame indexed by date with sunrise_h, sunset_h, daylight_h (local hours)."""
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    doy = dates.dayofyear.to_numpy()
    year_len = np.where(dates.is_leap_year, 366, 365)
    g = 2 * np.pi / year_len * (doy - 1)  # fractional year at local noon
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    lat = np.radians(LAT)
    cos_ha = np.cos(np.radians(ZENITH)) / (np.cos(lat) * np.cos(decl)) - np.tan(lat) * np.tan(decl)
    ha = np.degrees(np.arccos(np.clip(cos_ha, -1, 1)))
    sunrise_min = 720 - 4 * (LON + ha) - eqtime + UTC_OFFSET * 60
    sunset_min = 720 - 4 * (LON - ha) - eqtime + UTC_OFFSET * 60
    return pd.DataFrame({"sunrise_h": sunrise_min / 60, "sunset_h": sunset_min / 60,
                         "daylight_h": (sunset_min - sunrise_min) / 60}, index=dates.rename("date"))


_OBSERVED = None


def daylight_table(dates):
    """Open-Meteo values where the 2025 file has them, astronomical computation elsewhere."""
    global _OBSERVED
    if _OBSERVED is None:
        _OBSERVED = pd.read_csv(config.EXTERNAL / "daylight_moscow_2025.csv", parse_dates=["date"]).set_index("date")
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates).unique())).normalize()
    computed = sun_times(dates)
    return _OBSERVED.reindex(dates).combine_first(computed)[["sunrise_h", "sunset_h", "daylight_h"]]
