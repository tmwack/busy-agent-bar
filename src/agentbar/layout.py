"""Pure rendering: sessions -> BUSY Bar draw elements (dicts keyed by element id).

Region: max_tiles tiles side by side on the 72x16 front display; the rest of
the display is left to other applications. Each tile is a short label
(initials of the session name) above a row of small squares, one per running
subagent in that agent's state colour, above a thin bar in the session's own
state colour. The label takes the colour of the most active state of the
session and its agents. While a session works, its bar goes dark between two lit
end caps and a segment bounces between them; a working agent's square is dim
with one bright quarter stepping clockwise. shimmer_phase steps both through
four frames.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from .config import LayoutConfig
from .model import Agent, AgentState, Session

FRONT_WIDTH = 72
FRONT_HEIGHT = 16

# Words in kebab-case, snake_case, spaced, camelCase and PascalCase names.
# An acronym ends where a capitalised word starts: HTTPServer -> HTTP, Server.
WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z0-9]+")


def region_x(cfg: LayoutConfig) -> int:
    width = cfg.max_tiles * cfg.tile_width + (cfg.max_tiles - 1) * cfg.gap
    if width > FRONT_WIDTH:
        raise ValueError(f"{cfg.max_tiles} tiles x {cfg.tile_width}px does not fit in {FRONT_WIDTH}px")
    if cfg.x is None:
        return FRONT_WIDTH - width
    if cfg.x < 0 or cfg.x + width > FRONT_WIDTH:
        raise ValueError(f"region x={cfg.x} width={width} exceeds the display")
    return cfg.x


def select(sessions: list[Session], cfg: LayoutConfig) -> list[Session]:
    """Sessions that get a tile, in stable (first-seen) order."""
    pool = [s for s in sessions if cfg.show_idle or s.top_state is not AgentState.IDLE]
    if len(pool) > cfg.max_tiles:
        pool = sorted(pool, key=lambda s: (-s.top_state, s.first_seen))[: cfg.max_tiles]
    return sorted(pool, key=lambda s: s.first_seen)


def initials(name: str, n: int) -> str:
    """First letter of each word, lowercased, padded with "-" to n characters.

    With n=4: busy-agent-bar -> bab-, mcpTenancy -> mt--, agentbar -> a---
    """
    return "".join(w[0] for w in WORD.findall(name))[:n].lower().ljust(n, "-")


def labels(sessions: list[Session], n: int) -> list[str]:
    """Initials of the session title, else the cwd basename; duplicates get a 1-based suffix digit."""
    bases = []
    for s in sessions:
        name = s.title or os.path.basename((s.cwd or "").rstrip("/")) or s.session_id
        bases.append(initials(name, n))
    counts = Counter(bases)
    seen: Counter[str] = Counter()
    out = []
    for base in bases:
        if counts[base] > 1:
            seen[base] += 1
            out.append(base[: max(n - 1, 0)] + str(seen[base]))
        else:
            out.append(base)
    return out


def dim(color: str, factor: float) -> str:
    c = color.lstrip("#")
    rgb = (int(c[i : i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(v * factor):02X}" for v in rgb)


# Element ids double as z-order on the device (higher on top). Each tile has a block of
# 100: +0 bar, +1 label, +2/+3 end caps and +4 the moving segment while it works,
# +10.. agent squares, +20.. the bright pixel on each working agent's square.
CAP_LEFT, CAP_RIGHT, SEGMENT, AGENT, AGENT_PIXEL = 2, 3, 4, 10, 20
OFF = "#000000"


def element_ids(slot: int) -> tuple[str, str]:
    base = 100 * (slot + 1)
    return str(base), str(base + 1)


def element_id(slot: int, offset: int) -> str:
    return str(100 * (slot + 1) + offset)


def max_agents(cfg: LayoutConfig) -> int:
    # At most 10, so square ids (+10..+19) stay below the pixel ids (+20..).
    return min((cfg.tile_width + cfg.agent_gap) // (cfg.agent_size + cfg.agent_gap), 10)


def shown_agents(s: Session, cfg: LayoutConfig) -> list[Agent]:
    """Agents that get a square: the most active ones, in first-seen order."""
    agents = sorted(s.agents.values(), key=lambda a: (-a.state, a.first_seen))[: max_agents(cfg)]
    return sorted(agents, key=lambda a: a.first_seen)


def state_color(state: AgentState, cfg: LayoutConfig, blink_on: bool, text: bool = False) -> str:
    color = cfg.text_colors.get(state, cfg.colors[state]) if text else cfg.colors[state]
    if state is AgentState.NEEDS_INPUT and not blink_on:
        color = dim(color, cfg.dim_factor)
    return color


def rectangle(element_id: str, x: int, y: int, width: int, height: int, colors: list[str], fill: str = "solid") -> dict:
    return {
        "id": element_id,
        "type": "rectangle",
        "display": "front",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fill": fill,
        "fill_colors": colors,
        "border_width": 0,
    }


def bar_elements(s: Session, cfg: LayoutConfig, slot: int, x: int, blink_on: bool, phase: int) -> dict[str, dict]:
    """The session's bar; while it works, end caps and a segment bouncing between them.

    Bars are always a horizontal gradient; a solid bar is one colour to itself.
    Re-posting an element id updates the widget in place, and the firmware's solid fill
    (rectangle_widget_set_background in applications/services/canvas/widgets/
    rectangle.c) never resets an earlier gradient, so a bar that was ever a gradient
    must stay one.
    """
    y = FRONT_HEIGHT - cfg.bar_height
    w, h = cfg.tile_width, cfg.bar_height
    color = state_color(s.state, cfg, blink_on)
    bar_id = element_id(slot, 0)
    if not (cfg.shimmer and s.state is AgentState.WORKING):
        return {bar_id: rectangle(bar_id, x, y, w, h, [color, color], "gradient_h")}
    # Caps on the outer columns, a 1 px gap inside each, and the segment stepping
    # left, centre, right, centre.
    left, right = 2, w - 2 - cfg.shimmer_width
    pos = (left, (left + right) // 2, right, (left + right) // 2)[phase % 4]
    ids = [element_id(slot, o) for o in (CAP_LEFT, CAP_RIGHT, SEGMENT)]
    return {
        bar_id: rectangle(bar_id, x, y, w, h, [OFF, OFF], "gradient_h"),
        ids[0]: rectangle(ids[0], x, y, 1, h, [color]),
        ids[1]: rectangle(ids[1], x + w - 1, y, 1, h, [color]),
        ids[2]: rectangle(ids[2], x + pos, y, cfg.shimmer_width, h, [color]),
    }


def agent_elements(
    agents: list[Agent], cfg: LayoutConfig, slot: int, x: int, blink_on: bool, phase: int
) -> dict[str, dict]:
    """One square per agent. A working agent's square is dim with one bright quarter
    stepping clockwise; other states are solid (needs input blinks)."""
    size, y = cfg.agent_size, FRONT_HEIGHT - cfg.bar_height - cfg.agent_size
    q = max(size // 2, 1)
    dx, dy = ((0, 0), (q, 0), (q, q), (0, q))[phase % 4]  # clockwise from top left
    out: dict[str, dict] = {}
    for i, agent in enumerate(agents):
        ax = x + i * (size + cfg.agent_gap)
        color = state_color(agent.state, cfg, blink_on)
        square_id = element_id(slot, AGENT + i)
        if not (cfg.shimmer and agent.state is AgentState.WORKING):
            out[square_id] = rectangle(square_id, ax, y, size, size, [color])
            continue
        pixel_id = element_id(slot, AGENT_PIXEL + i)
        out[square_id] = rectangle(square_id, ax, y, size, size, [dim(color, cfg.shimmer_factor)])
        out[pixel_id] = rectangle(pixel_id, ax + dx, y + dy, q, q, [color])
    return out


def render(
    sessions: list[Session], cfg: LayoutConfig, blink_on: bool = True, shimmer_phase: int = 0
) -> dict[str, dict]:
    shown = select(sessions, cfg)
    x0 = region_x(cfg)
    out: dict[str, dict] = {}
    for slot, (s, label) in enumerate(zip(shown, labels(shown, cfg.name_chars), strict=True)):
        x = x0 + slot * (cfg.tile_width + cfg.gap)
        _, text_id = element_ids(slot)
        out.update(bar_elements(s, cfg, slot, x, blink_on, shimmer_phase))
        out.update(agent_elements(shown_agents(s, cfg), cfg, slot, x, blink_on, shimmer_phase))
        out[text_id] = {
            "id": text_id,
            "type": "text",
            "display": "front",
            "x": x,
            "y": cfg.text_y,
            "width": cfg.tile_width,
            "text": label,
            "font": cfg.font,
            "color": state_color(s.top_state, cfg, blink_on, text=True),
        }
    return out


def blinking(sessions: list[Session], cfg: LayoutConfig) -> bool:
    return any(s.top_state is AgentState.NEEDS_INPUT for s in select(sessions, cfg))


def shimmering(sessions: list[Session], cfg: LayoutConfig) -> bool:
    """True if a shown session or a shown agent is working, so frames must advance."""
    return cfg.shimmer and any(
        s.state is AgentState.WORKING or any(a.state is AgentState.WORKING for a in shown_agents(s, cfg))
        for s in select(sessions, cfg)
    )
