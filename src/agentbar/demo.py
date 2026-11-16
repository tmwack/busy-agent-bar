"""Scripted demo: scenes played into a registry the daemon renders instead of the real one.

Each scene is a list of timed steps of real AgentEvents, so the demo goes through the
same registry, layout and sink as live sessions. `agentbar demo` asks the daemon to
play it; real sessions keep being tracked and come back when it ends.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace

from .model import AgentEvent, AgentState, EventKind
from .registry import Registry

SOURCE = "demo"
TITLES = {"demo-1": "agent bar", "demo-2": "web app", "demo-3": "data job"}  # ab--, wa--, dj--

WORK, ASK, DONE, IDLE = AgentState.WORKING, AgentState.NEEDS_INPUT, AgentState.DONE, AgentState.IDLE


def state(session: str, s: AgentState, agent: str | None = None) -> AgentEvent:
    """A state change for a demo session, or for one of its agents."""
    return AgentEvent(
        SOURCE,
        session,
        EventKind.STATE,
        0.0,  # stamped when played
        state=s,
        title=TITLES[session],
        agent_id=agent,
        agent_type="demo" if agent else None,
    )


def end(session: str, agent: str | None = None) -> AgentEvent:
    """A demo session ends, or one of its agents stops."""
    return AgentEvent(SOURCE, session, EventKind.END, 0.0, agent_id=agent)


@dataclass(frozen=True)
class Step:
    at: float  # seconds from the start of the scene
    events: tuple[AgentEvent, ...]
    caption: str | None = None


SCENES: dict[str, tuple[Step, ...]] = {
    "states": (
        Step(0, (state("demo-1", WORK),), "Working: green, a segment bounces between the end caps"),
        Step(4, (state("demo-1", ASK),), "Needs input: amber, blinking"),
        Step(7, (state("demo-1", DONE),), "Done: a full, still green bar"),
        Step(10, (state("demo-1", IDLE),), "Idle: dim steel blue (normally an hour after done)"),
        Step(12, (state("demo-2", WORK), state("demo-3", ASK)), "Three sessions side by side"),
        Step(16, (end("demo-1"), end("demo-2"), end("demo-3"))),
    ),
    "agents": (
        Step(0, (state("demo-1", WORK),), "A session at work"),
        Step(1, (state("demo-1", WORK, "a1"),), "Subagents: one spinning square each"),
        Step(1.5, (state("demo-1", WORK, "a2"),)),
        Step(2, (state("demo-1", WORK, "a3"),)),
        Step(5, (state("demo-1", ASK, "a2"),), "An agent needs you: its square and the label blink amber"),
        Step(8, (state("demo-1", WORK, "a2"),), "Approved"),
        Step(9, (state("demo-1", DONE),), "Main turn done: solid green bar, agents still spinning"),
        Step(11, (end("demo-1", "a1"),), "Each finished agent pulses, then goes"),
        Step(12.5, (end("demo-1", "a2"),)),
        Step(14, (end("demo-1", "a3"),)),
        Step(16, (end("demo-1"),)),
    ),
}


def duration(scenes: Sequence[str]) -> float:
    return sum(SCENES[name][-1].at for name in scenes)


async def play(
    registry: Registry,
    scenes: Sequence[str],
    *,
    loop: bool = False,
    on_step: Callable[[str, Step], Awaitable[None]] | None = None,
    time_scale: float = 1.0,  # tests only: shrink the waits
) -> None:
    """Apply each step's events at its time, scene after scene; repeat if loop."""
    while True:
        for name in scenes:
            start = time.monotonic()
            for step in SCENES[name]:
                delay = start + step.at * time_scale - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                now = time.time()
                for ev in step.events:
                    registry.apply(replace(ev, ts=now))
                if on_step is not None:
                    await on_step(name, step)
        if not loop:
            return
