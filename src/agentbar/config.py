"""Config: ~/.config/agentbar/config.toml (override with AGENTBAR_CONFIG). All keys optional."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .model import AgentState
from .paths import config_path

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Values are what is sent; the front display applies gamma 2.8, so they land darker and
# more saturated (#FFC000 shows as about #FFB300). Amber, not red, for needs input: the
# bar's own BUSY focus timer is red. Colours run warm to cool, and bright to dim, from
# needs attention to done: amber needs input, green working (shimmering), cyan done, and
# idle a faded done.
DEFAULT_COLORS = {
    AgentState.IDLE: "#385868",
    AgentState.DONE: "#00B0FF",
    AgentState.WORKING: "#00C850",
    AgentState.NEEDS_INPUT: "#FFC000",
}

# Label colours that differ from the bar colour. The idle bar (#385868) drives about 5%
# luminance, too dim for a readable label; #6090A8 drives about 18%, half of done cyan.
DEFAULT_TEXT_COLORS = {
    AgentState.IDLE: "#6090A8",
}


@dataclass
class BusyBarConfig:
    host: str = "10.0.4.20"  # USB address; set the bar's LAN IP for Wi-Fi
    token: str | None = None  # local HTTP API key (Wi-Fi only)
    application_name: str = "agentbar"
    priority: int = 50  # a running BUSY session sits above this, so we yield
    timeout_s: float = 2.0


@dataclass
class LayoutConfig:
    x: int | None = None  # left edge of the region; None = right-aligned
    tile_width: int = 18
    gap: int = 1
    max_tiles: int = 3
    name_chars: int = 4  # label length: initials, padded with "-"; 4 fit 18 px in the condensed font
    font: str = "condensed"  # busy_condensed_7: 4 px wide glyphs, ink on rows 2-8 below text_y (descenders 9-10)
    text_y: int = 0
    bar_height: int = 2
    agent_size: int = 2  # subagent squares, sitting on top of the bar
    agent_gap: int = 1
    show_idle: bool = True
    dim_factor: float = 0.2  # blink "off" brightness for NEEDS_INPUT
    shimmer: bool = True  # animate WORKING: a bouncing segment on the bar, a spinning pixel on agent squares
    shimmer_width: int = 5  # width of the bouncing segment
    shimmer_factor: float = 0.6  # brightness of a working agent's square behind its bright pixel
    colors: dict[AgentState, str] = field(default_factory=lambda: dict(DEFAULT_COLORS))
    text_colors: dict[AgentState, str] = field(default_factory=lambda: dict(DEFAULT_TEXT_COLORS))


@dataclass
class TimingConfig:
    done_decay_s: float = 3600  # DONE -> IDLE; an hour, so a finished session is still green after a meeting
    session_ttl_s: float = 7200  # expiry for sessions with no known PID
    blink_period_s: float = 1.0
    shimmer_step_s: float = 1.0  # seconds per shimmer frame; four frames per bounce
    busy_retry_s: float = 5.0  # retry interval while yielding / bar unreachable
    refresh_s: float = 60.0  # periodic full redraw to self-heal


@dataclass
class Config:
    busybar: BusyBarConfig = field(default_factory=BusyBarConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)


def _apply(target: object, table: dict, section: str) -> None:
    known = {f.name for f in fields(target)}
    for key, value in table.items():
        if key not in known:
            raise ValueError(f"unknown config key [{section}].{key}")
        if key in ("colors", "text_colors"):
            for name, color in value.items():
                if not HEX_COLOR.match(color):
                    raise ValueError(f"[{section}.{key}].{name} must be #RRGGBB")
                getattr(target, key)[AgentState[name.upper()]] = color
            continue
        setattr(target, key, value)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    cfg = Config()
    if not path.exists():
        return cfg
    data = tomllib.loads(path.read_text())
    unknown = set(data) - {"busybar", "layout", "timing"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    for section in ("busybar", "layout", "timing"):
        if section in data:
            _apply(getattr(cfg, section), data[section], section)
    return cfg
