"""Example user skill: current weather from Open-Meteo (free, no API key).

Install: copy this file into your skills folder and restart PocketAgent
    Windows:      %APPDATA%\\PocketAgent\\skills\\
    macOS/Linux:  ~/.pocketagent/skills/
Then ask: "How is the weather in Istanbul?"
"""

import requests

from pocketagent.tools import tool

WEATHER_CODES = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
                 51: "light drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow",
                 73: "snow", 75: "heavy snow", 80: "rain showers", 95: "thunderstorm"}


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: city name, e.g. "Istanbul" or "London"
    """
    places = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                          params={"name": city, "count": 1}, timeout=15).json().get("results")
    if not places:
        return f"I could not find a place called {city}."
    place = places[0]
    current = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"}).json()["current"]
    sky = WEATHER_CODES.get(current["weather_code"], "unknown conditions")
    return (f"{place['name']}, {place.get('country', '')}: {current['temperature_2m']} °C, {sky}, "
            f"humidity {current['relative_humidity_2m']}%, wind {current['wind_speed_10m']} km/h")
