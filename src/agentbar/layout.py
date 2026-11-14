"""Pure rendering: sessions -> BUSY Bar draw elements (dicts keyed by element id).

Region: max_tiles tiles side by side on the 72x16 front display; the rest of
the display is left to other applications. Each tile is a short label
(initials of the session name) above a row of small squares, one per running
subagent in that agent's state colour, above a thin bar in the session's own
state colour. The label takes the colour of the most active state of the
session and its agents. A WORKING bar shimmers: its horizontal gradient flips
direction with shimmer_phase.
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


def element_ids(slot: int) -> tuple[str, str]:
    # Element ids double as z-order on the device (higher on top).
    base = 10 * (slot + 1)
    return str(base), str(base + 1)


def agent_ids(slot: int, n: int) -> list[str]:
    return [str(10 * (slot + 1) + 2 + i) for i in range(n)]


def max_agents(cfg: LayoutConfig) -> int:
    # At most 8, so square ids (+2..+9) stay inside the tile's block of 10.
    return min((cfg.tile_width + cfg.agent_gap) // (cfg.agent_size + cfg.agent_gap), 8)


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


def bar_fill(s: Session, cfg: LayoutConfig, blink_on: bool, shimmer_phase: int) -> tuple[str, list[str]]:
    color = state_color(s.state, cfg, blink_on)
    if not (cfg.shimmer and s.state is AgentState.WORKING):
        return "solid", [color]
    colors = [color, dim(color, cfg.shimmer_factor)]
    return "gradient_h", colors[::-1] if shimmer_phase % 2 else colors


def render(
    sessions: list[Session], cfg: LayoutConfig, blink_on: bool = True, shimmer_phase: int = 0
) -> dict[str, dict]:
    shown = select(sessions, cfg)
    x0 = region_x(cfg)
    out: dict[str, dict] = {}
    for slot, (s, label) in enumerate(zip(shown, labels(shown, cfg.name_chars), strict=True)):
        x = x0 + slot * (cfg.tile_width + cfg.gap)
        bar_id, text_id = element_ids(slot)
        fill, colors = bar_fill(s, cfg, blink_on, shimmer_phase)
        out[bar_id] = rectangle(bar_id, x, FRONT_HEIGHT - cfg.bar_height, cfg.tile_width, cfg.bar_height, colors, fill)
        agents = shown_agents(s, cfg)
        for i, (agent, agent_id) in enumerate(zip(agents, agent_ids(slot, len(agents)), strict=True)):
            out[agent_id] = rectangle(
                agent_id,
                x + i * (cfg.agent_size + cfg.agent_gap),
                FRONT_HEIGHT - cfg.bar_height - cfg.agent_size,
                cfg.agent_size,
                cfg.agent_size,
                [state_color(agent.state, cfg, blink_on)],
            )
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
    return cfg.shimmer and any(s.state is AgentState.WORKING for s in select(sessions, cfg))
