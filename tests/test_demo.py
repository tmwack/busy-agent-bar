import asyncio
import json
import time
from dataclasses import replace

import pytest
from busylib.types import DisplayElements

from agentbar import demo
from agentbar.config import Config, LayoutConfig
from agentbar.daemon import Daemon
from agentbar.layout import render
from agentbar.model import AgentEvent, AgentState, EventKind
from agentbar.registry import Registry

CFG = LayoutConfig()
COLORS = CFG.colors


def replay(scene):
    """Yield (step, registry, now) after applying each step of a scene."""
    registry = Registry(3600, 7200, is_alive=lambda _: True, agent_pulse_s=1.0)
    for step in demo.SCENES[scene]:
        now = 1000 + step.at
        for ev in step.events:
            registry.apply(replace(ev, ts=now))
        yield step, registry, now


def frames(scene):
    return {
        step.caption: (registry, render(registry.sessions(), CFG, now=now))
        for step, registry, now in replay(scene)
        if step.caption
    }


@pytest.mark.parametrize("scene", list(demo.SCENES))
def test_scene_is_in_time_order_short_and_cleans_up(scene):
    times = [step.at for step in demo.SCENES[scene]]
    assert times == sorted(times)
    assert times[-1] < 20  # Tyler's limit; 15 s is the target
    *_, (_, registry, _) = replay(scene)
    assert registry.sessions() == []


@pytest.mark.parametrize("scene", list(demo.SCENES))
def test_every_step_renders_valid_elements(scene):
    for _, registry, now in replay(scene):
        elements = render(registry.sessions(), CFG, now=now)
        if not elements:  # the scene's final step ends every session
            continue
        DisplayElements.model_validate({"application_name": "agentbar", "elements": list(elements.values())})


def test_states_scene_key_frames():
    f = frames("states")
    _, out = f["Needs input: amber, blinking"]
    assert out["101"]["color"] == COLORS[AgentState.NEEDS_INPUT]
    _, out = f["Done: a full, still green bar"]
    assert out["100"]["fill_colors"] == [COLORS[AgentState.DONE]] * 2
    _, out = f["Three sessions side by side"]
    assert [out[i]["text"] for i in ("101", "201", "301")] == ["ab--", "wa--", "dj--"]


def test_agents_scene_key_frames():
    f = frames("agents")
    registry, out = f["An agent needs you: its square and the label blink amber"]
    assert {"110", "111", "112"} <= out.keys()
    assert out["101"]["color"] == COLORS[AgentState.NEEDS_INPUT]
    assert out["111"]["fill_colors"] == [COLORS[AgentState.NEEDS_INPUT]]
    registry, out = f["Main turn done: solid green bar, agents still spinning"]
    assert out["100"]["fill_colors"] == [COLORS[AgentState.DONE]] * 2
    assert {"110", "111", "112", "120"} <= out.keys()  # squares, with a spinning pixel
    # Replay up to the last agent's stop, before the session itself ends.
    _, registry, now = next(
        (step, reg, ts)
        for step, reg, ts in replay("agents")
        if step.events[0].agent_id == "a3" and step.events[0].kind is EventKind.END
    )
    assert registry.sessions()[0].agents["a3"].ended_at == now  # pulsing
    registry.tick(now + 1.0)  # its pulse is over
    assert registry.sessions()[0].agents == {}


class RecordingSink:
    blocked = False
    reachable = True

    def __init__(self):
        self.labels: list[set[str]] = []

    def invalidate(self):
        pass

    async def reset(self):
        pass

    async def screen(self):
        return None

    async def apply(self, desired):
        self.labels.append({e["text"] for e in desired.values() if e["type"] == "text"})


class FakeWriter:
    def __init__(self):
        self.lines: list[dict] = []

    def write(self, data):
        self.lines.extend(json.loads(line) for line in data.splitlines())

    async def drain(self):
        pass


class StayingClient:
    async def read(self):
        await asyncio.Event().wait()  # never disconnects


def test_daemon_demo_hides_real_tiles_then_restores_them():
    async def go():
        sink = RecordingSink()
        d = Daemon(Config(), sink)
        real = AgentEvent("cc", "real", EventKind.STATE, time.time(), state=AgentState.WORKING, cwd="/w/real-proj")
        d.registry.apply(real)
        loop = asyncio.ensure_future(d._render_loop())
        await asyncio.sleep(0.05)
        first, second = FakeWriter(), FakeWriter()
        msg = {"type": "demo", "scenes": ["states"], "time_scale": 0.01}
        playing = asyncio.ensure_future(d._run_demo(msg, StayingClient(), first))
        await asyncio.sleep(0.03)
        assert d.status()["demo"]
        await d._run_demo(msg, StayingClient(), second)  # refused while one plays
        await playing
        await asyncio.sleep(0.05)
        d.stop()
        await loop
        return sink.labels, first.lines, second.lines

    labels, first, second = asyncio.run(go())
    assert labels[0] == {"rp--"}
    assert any("ab--" in frame and "rp--" not in frame for frame in labels)  # demo replaced the real tile
    assert labels[-1] == {"rp--"}  # and it came back
    assert [line["caption"] for line in first[:2]] == [
        "Working: green, a segment bounces between the end caps",
        "Needs input: amber, blinking",
    ]
    assert first[-1] == {"done": True}
    assert second == [{"error": "a demo is already running"}]
