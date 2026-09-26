"""External sources #3 (weather) and #4 (daylight): Moscow 2025 from the Open-Meteo archive (ERA5).

https://open-meteo.com/en/docs/historical-weather-api — free, no key.
Weather for Nov–Dec is ex-post observation (not available on 2025-10-31).
Sunrise/sunset are astronomical and known in advance, so daylight features carry no leakage.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src import config

BASE = ("https://archive-api.open-meteo.com/v1/archive?latitude=55.75&longitude=37.62"
        "&start_date=2025-01-01&end_date=2025-12-31&timezone=Europe%2FMoscow")
HOURLY = "&hourly=temperature_2m,precipitation,rain,snowfall,snow_depth,wind_speed_10m,apparent_temperature"
DAILY = "&daily=sunrise,sunset,daylight_duration"


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


config.EXTERNAL.mkdir(parents=True, exist_ok=True)

hourly = pd.DataFrame(get(BASE + HOURLY)["hourly"])
hourly["time"] = pd.to_datetime(hourly.time)
hourly.insert(0, "date", hourly.time.dt.normalize())
hourly.insert(1, "hour", hourly.time.dt.hour)
out = config.EXTERNAL / "weather_moscow_2025_hourly.csv"
hourly.drop(columns="time").to_csv(out, index=False)
print(out, hourly.shape, hourly.isna().sum().sum(), "NaN")

daily = pd.DataFrame(get(BASE + DAILY)["daily"]).rename(columns={"time": "date"})
daily["sunrise"] = pd.to_datetime(daily.sunrise)
daily["sunset"] = pd.to_datetime(daily.sunset)
daily["sunrise_h"] = daily.sunrise.dt.hour + daily.sunrise.dt.minute / 60
daily["sunset_h"] = daily.sunset.dt.hour + daily.sunset.dt.minute / 60
daily["daylight_h"] = daily.daylight_duration / 3600
out = config.EXTERNAL / "daylight_moscow_2025.csv"
daily[["date", "sunrise_h", "sunset_h", "daylight_h"]].to_csv(out, index=False)
print(out, daily.shape)
