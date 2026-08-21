"""One-line weather for the morning brief, via Open-Meteo (no API key)."""

from __future__ import annotations

import requests

from .config import Config

_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 61: "light rain",
    63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    80: "showers", 95: "thunderstorms",
}


def one_liner(cfg: Config) -> str | None:
    if not cfg.lat or not cfg.lon:
        return None
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": cfg.lat,
                "longitude": cfg.lon,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        cur = data.get("current", {})
        daily = data.get("daily", {})
        cond = _CODES.get(int(cur.get("weather_code", -1)), "—")
        now = round(cur.get("temperature_2m", 0))
        hi = round(daily.get("temperature_2m_max", [0])[0])
        lo = round(daily.get("temperature_2m_min", [0])[0])
        return f"{cond}, {now}°F now (high {hi} / low {lo})"
    except Exception:
        return None
