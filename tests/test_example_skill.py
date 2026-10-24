"""The example skill in examples/skills must keep working, since people copy it."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pocketagent.tools import ToolContext, ToolRegistry

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "skills"


def fake_get(url, params, timeout):
    if "geocoding" in url:
        body = {"results": [{"name": "Istanbul", "country": "Türkiye", "latitude": 41.01, "longitude": 28.97}]}
    else:
        body = {"current": {"temperature_2m": 17.4, "relative_humidity_2m": 72,
                            "wind_speed_10m": 11.2, "weather_code": 3}}
    return SimpleNamespace(json=lambda: body)


def test_weather_example_loads_and_answers(tmp_path):
    registry = ToolRegistry()
    registry.load_folder(EXAMPLES)
    assert registry.errors == []
    with patch("requests.get", side_effect=fake_get):
        result = registry.call("get_weather", {"city": "Istanbul"}, ToolContext(workspace=tmp_path))
    assert result == "Istanbul, Türkiye: 17.4 °C, overcast, humidity 72%, wind 11.2 km/h"
