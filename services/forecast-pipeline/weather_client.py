"""Fetch 15-minute weather forecasts for the next 48 hours from Open-Meteo.

Includes the solar variables needed to forecast what solar panels generate.
The variables and the time alignment should be the same as in the meter readings, 
so they can be compared/easily be used for the machine learning model.
To get the weather forecasts from Benthuizen for the next 48 hours, you only have to call the
get_weather() function, this will return the values in json.
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

BENTHUIZEN = (52.08, 4.55)

# Solar: global horizontal (GHI), direct and diffuse radiation in W/m², and
# sunshine_duration = seconds of the quarter hour with real sunshine (0-900).
# SOLAR_VARS = ["shortwave_radiation", "direct_radiation", "diffuse_radiation", "sunshine_duration"]
# OTHER_VARS = ["temperature_2m", "precipitation", "weather_code"]

SOLAR_VARS = ["shortwave_radiation"]
OTHER_VARS = ["temperature_2m"]

# Open-Meteo averages (or sums) these over the 15 minutes BEFORE the timestamp:
# the value at 12:15 describes 12:00-12:15. The meter readings use the START of
# the quarter hour, so these values are moved 15 minutes back.
BACKWARD_VARS = [*SOLAR_VARS, "precipitation"]


def get_json(base_url, params):
    url = f"{base_url}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc
    if data.get("error"):
        raise RuntimeError(data.get("reason", "Open-Meteo returned an error"))
    return data


def geocode(location):
    data = get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": location, "count": 1, "language": "en", "format": "json"},
    )
    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"Location not found: {location}")
    place = results[0]
    label = ", ".join(
        value for value in (place.get("name"), place.get("admin1"), place.get("country")) if value
    )
    return place["latitude"], place["longitude"], label


def get_forecast(latitude, longitude):
    data = get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": latitude,
            "longitude": longitude,
            "minutely_15": ",".join([*OTHER_VARS, *SOLAR_VARS]),
            "forecast_days": 3,  # one day extra, so the last quarters of the 48 hours are present, else they are missing when the forecast is requested at 23:45
            "timezone": "UTC",
        },
    )
    quarters = data["minutely_15"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in quarters["time"]]
    by_time = {t: i for i, t in enumerate(times)}

    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % 15)  # start of the current quarter hour
    end = start + timedelta(hours=48)
    forecast = []

    for index, timestamp in enumerate(times):
        if not start <= timestamp < end:
            continue
        # Value that describes this quarter hour: 15 minutes later for backward-averaged variables
        later = by_time.get(timestamp + timedelta(minutes=15))
        if later is None:
            continue
        row = {"time": timestamp.isoformat()}
        for var in [*OTHER_VARS, *SOLAR_VARS]:
            row[var] = quarters[var][later if var in BACKWARD_VARS else index]
        forecast.append(row)
    return forecast


def get_weather(location=None):
    """Forecast for a place name, or for Benthuizen when no location is given."""
    if location:
        latitude, longitude, label = geocode(location)
    else:
        (latitude, longitude), label = BENTHUIZEN, "Benthuizen, South Holland, Netherlands"
    return {
        "location": label,
        "latitude": latitude,
        "longitude": longitude,
        "forecast": get_forecast(latitude, longitude),
    }
