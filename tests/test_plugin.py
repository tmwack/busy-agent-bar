import asyncio
import json
import time
from datetime import datetime

import pytest

from agentbar import plugin
from agentbar.config import Config, PluginConfig
from agentbar.daemon import Daemon


def test_plain_text_is_one_white_text_element():
    [e] = plugin.parse("9:41\nignored second line\n", 16)
    assert e == {
        "id": "900",
        "z_index": 900,
        "type": "text",
        "display": "front",
        "x": 0,
        "y": 4,
        "text": "9:41",
        "font": "small",
        "color": "#FFFFFF",
        "width": 16,
    }


def test_json_elements_are_clipped_and_numbered():
    out = json.dumps(
        {
            "elements": [
                {"type": "rectangle", "x": 10, "y": 12, "width": 20, "height": 9, "fill_colors": ["#00FF00"]},
                {"type": "text", "x": 2, "y": 0, "text": "hi", "width": 40, "id": "mine", "scroll_rate": 5},
            ]
        }
    )
    rect, text = plugin.parse(out, 16)
    assert (rect["id"], rect["z_index"], text["id"], text["z_index"]) == ("900", 900, "901", 901)
    assert (rect["width"], rect["height"]) == (6, 4)  # clipped to the 16x16 area
    assert rect["fill"] == "gradient_h" and rect["fill_colors"] == ["#00FF00", "#00FF00"]
    assert text["width"] == 14 and "scroll_rate" not in text  # fields outside the contract are dropped


def test_xpm_bitmaps_must_fit():
    xpm = "! XPM2\n4 2 2 1\n. c none\n# c #FF0000\n#..#\n.##.\n"
    [e] = plugin.parse(json.dumps({"elements": [{"type": "xpmbitmap", "x": 12, "y": 0, "data": xpm}]}), 16)
    assert e["data"] == xpm
    with pytest.raises(plugin.PluginError, match="doesn't fit"):
        plugin.parse(json.dumps({"elements": [{"type": "xpmbitmap", "x": 13, "y": 0, "data": xpm}]}), 16)


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("", "no output"),
        ("{not json", "bad JSON"),
        ('{"elements": []}', "non-empty"),
        (json.dumps({"elements": [{"type": "image", "x": 0, "y": 0}]}), "element types"),
        (json.dumps({"elements": [{"type": "text", "x": 16, "y": 0, "text": "x"}]}), "outside"),
        (
            json.dumps({"elements": [{"type": "text", "x": 0, "y": 0, "text": "x", "color": "#ZZZZZZ"}]}),
            "not a valid color",
        ),
        (json.dumps({"elements": [{"type": "text", "x": 0, "y": 0, "text": "x"}] * 21}), "the most is 20"),
    ],
)
def test_unusable_output_is_an_error(output, message):
    with pytest.raises(plugin.PluginError, match=message):
        plugin.parse(output, 16)


def test_error_mark_is_an_amber_exclamation_mark():
    bar, dot = plugin.error_mark(16)
    assert (bar["x"], bar["y"], bar["height"], dot["y"], dot["height"]) == (8, 4, 5, 10, 1)
    assert bar["fill_colors"] == [plugin.ERROR_COLOR] * 2


class NullSink:
    blocked = False
    reachable = True

    def invalidate(self):
        pass

    async def reset(self):
        pass

    async def apply(self, desired):
        pass


def run_plugin_once(command, timeout_s=2.0):
    """Start the plugin runner, wait for its first result, stop it."""

    async def go():
        d = Daemon(Config(plugin=PluginConfig(command=command, interval_s=30, timeout_s=timeout_s)), NullSink())
        task = asyncio.ensure_future(d._run_plugin())
        while d.plugin_status is None:
            await asyncio.sleep(0.01)
        d.stop()
        await task
        return d

    return asyncio.run(go())


def test_plugin_output_is_drawn_and_reported_ok():
    d = run_plugin_once("echo 9:41")
    assert [e["text"] for e in d._plugin_elements.values()] == ["9:41"]
    assert d.status()["plugin"]["error"] is None


def test_failing_plugin_shows_the_error_mark():
    d = run_plugin_once("echo boom >&2; exit 3")
    assert list(d._plugin_elements.values()) == plugin.error_mark(16)
    assert d.status()["plugin"]["error"] == "exit status 3: boom"


def test_slow_plugin_is_killed_on_timeout():
    started = time.monotonic()
    d = run_plugin_once("sleep 5; echo late", timeout_s=0.2)
    assert time.monotonic() - started < 2
    assert d.status()["plugin"]["error"] == "timed out after 0.2 s"


def test_builtin_clock_shows_the_time_and_the_hour_passing():
    text, line = plugin.parse(plugin.clock_output(datetime(2026, 11, 18, 10, 20), 16), 16)
    assert (text["text"], text["color"], text["y"]) == ("10:20", plugin.CLOCK_COLOR, 3)
    assert (line["width"], line["y"]) == (6, 14)  # 20 minutes of 60 across 16 columns, plus one
    _, full = plugin.parse(plugin.clock_output(datetime(2026, 11, 18, 9, 59), 16), 16)
    assert full["width"] == 16


def test_no_command_runs_the_builtin_clock():
    d = run_plugin_once(None)
    [text, _] = d._plugin_elements.values()
    assert ":" in text["text"]
    assert d.status()["plugin"] == {**d.status()["plugin"], "command": plugin.BUILTIN_CLOCK, "error": None}


def test_disabled_plugin_draws_nothing():
    async def go():
        d = Daemon(Config(plugin=PluginConfig(enabled=False)), NullSink())
        await asyncio.wait_for(d._run_plugin(), 1)  # returns at once
        return d

    d = asyncio.run(go())
    assert d._plugin_elements == {} and d.status()["plugin"] is None
