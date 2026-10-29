"""Pure rendering: sessions -> BUSY Bar draw elements (dicts keyed by element id).

Region: max_tiles tiles side by side on the 72x16 front display; the rest of
the display is left to other applications. Each tile is the project name
(text, state colour) above a thin bar in the state colour.
"""

from __future__ import annotations

import os
from collections import Counter

from .config import LayoutConfig
from .model import AgentState, Session

FRONT_WIDTH = 72
FRONT_HEIGHT = 16


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
    pool = [s for s in sessions if cfg.show_idle or s.state is not AgentState.IDLE]
    if len(pool) > cfg.max_tiles:
        pool = sorted(pool, key=lambda s: (-s.state, s.first_seen))[: cfg.max_tiles]
    return sorted(pool, key=lambda s: s.first_seen)


def labels(sessions: list[Session], n: int) -> list[str]:
    """Truncated project names; duplicates get a 1-based suffix digit."""
    bases = []
    for s in sessions:
        name = os.path.basename((s.cwd or "").rstrip("/")) or s.session_id
        bases.append(name[:n])
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


def render(sessions: list[Session], cfg: LayoutConfig, blink_on: bool = True) -> dict[str, dict]:
    shown = select(sessions, cfg)
    x0 = region_x(cfg)
    out: dict[str, dict] = {}
    for slot, (s, label) in enumerate(zip(shown, labels(shown, cfg.name_chars), strict=True)):
        color = cfg.colors[s.state]
        if s.state is AgentState.NEEDS_INPUT and not blink_on:
            color = dim(color, cfg.dim_factor)
        x = x0 + slot * (cfg.tile_width + cfg.gap)
        bar_id, text_id = element_ids(slot)
        out[bar_id] = {
            "id": bar_id,
            "type": "rectangle",
            "display": "front",
            "x": x,
            "y": FRONT_HEIGHT - cfg.bar_height,
            "width": cfg.tile_width,
            "height": cfg.bar_height,
            "fill": "solid",
            "fill_colors": [color],
            "border_width": 0,
        }
        out[text_id] = {
            "id": text_id,
            "type": "text",
            "display": "front",
            "x": x,
            "y": cfg.text_y,
            "width": cfg.tile_width,
            "text": label,
            "font": cfg.font,
            "color": color,
        }
    return out


def blinking(sessions: list[Session], cfg: LayoutConfig) -> bool:
    return any(s.state is AgentState.NEEDS_INPUT for s in select(sessions, cfg))
