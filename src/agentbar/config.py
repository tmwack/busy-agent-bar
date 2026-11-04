"""Config: ~/.config/agentbar/config.toml (override with AGENTBAR_CONFIG). All keys optional."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .model import AgentState
from .paths import config_path

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_COLORS = {
    AgentState.IDLE: "#303030",
    AgentState.DONE: "#00C850",
    AgentState.WORKING: "#FFA000",
    AgentState.NEEDS_INPUT: "#FF1E1E",
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
    name_chars: int = 3  # label length: initials, padded with "-"
    font: str = "small"
    text_y: int = 1
    bar_height: int = 2
    show_idle: bool = True
    dim_factor: float = 0.2  # blink "off" brightness for NEEDS_INPUT
    colors: dict[AgentState, str] = field(default_factory=lambda: dict(DEFAULT_COLORS))


@dataclass
class TimingConfig:
    done_decay_s: float = 300  # DONE -> IDLE
    session_ttl_s: float = 7200  # expiry for sessions with no known PID
    blink_period_s: float = 1.0
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
        if key == "colors":
            for name, color in value.items():
                if not HEX_COLOR.match(color):
                    raise ValueError(f"[{section}.colors].{name} must be #RRGGBB")
                target.colors[AgentState[name.upper()]] = color  # type: ignore[attr-defined]
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
