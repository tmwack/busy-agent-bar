"""Config: ~/.config/agentbar/config.toml (override with AGENTBAR_CONFIG). All keys optional."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .model import AgentState
from .paths import config_path

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# A project icon replaces the label and must stay in the label's rows (2-9), so at most
# 8 rows; it can use the tile's full width.
ICON_MAX_ROWS = 8

# Values are what is sent; the front display applies gamma 2.8, so they land darker and
# more saturated (#FFC000 shows as about #FFB300). Amber, not red, for needs input: the
# bar's own BUSY focus timer is red. Amber needs input, green working and done (working
# moves, done is a still, solid bar), and a dim steel-blue idle.
DEFAULT_COLORS = {
    AgentState.IDLE: "#385868",
    AgentState.DONE: "#00C850",
    AgentState.WORKING: "#00C850",
    AgentState.NEEDS_INPUT: "#FFC000",
}

# Label colours that differ from the bar colour. The idle bar (#385868) drives about 5%
# luminance, too dim for a readable label; #6090A8 drives about 18%, half of done green.
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
    # Project folder (absolute) -> icon mask rows of "#" (lit) and "." (off). From the
    # [projects."<path>"] tables, not [layout].
    icons: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass
class TimingConfig:
    done_decay_s: float = 3600  # DONE -> IDLE; an hour, so a finished session is still green after a meeting
    session_ttl_s: float = 7200  # expiry for sessions with no known PID
    blink_period_s: float = 1.0
    shimmer_step_s: float = 1.0  # seconds per animation frame; six per bounce, four per spin
    agent_pulse_s: float = 1.0  # a finished agent's square: bright for half, dim for half, then gone
    busy_retry_s: float = 5.0  # retry interval while yielding / bar unreachable
    refresh_s: float = 60.0  # periodic full redraw to self-heal


BUILTIN_PLUGINS = ("clock", "tokens")


@dataclass
class PluginConfig:
    enabled: bool = True  # false: no plugin, and the bar's home screen shows when no session has a tile
    builtin: str = "clock"  # "clock", or "tokens" (today's Claude Code tokens)
    command: str | None = None  # replaces the built-in; run with /bin/sh -c, use absolute paths
    interval_s: float = 30.0
    timeout_s: float = 5.0


@dataclass
class Config:
    busybar: BusyBarConfig = field(default_factory=BusyBarConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    plugin: PluginConfig = field(default_factory=PluginConfig)


def _apply(target: object, table: dict, section: str) -> None:
    known = {f.name for f in fields(target)}
    for key, value in table.items():
        if key not in known:
            raise ValueError(f"unknown config key [{section}].{key}")
        if key == "icons":
            raise ValueError('icons go in [projects."<folder>"] tables, not [layout]')
        if key in ("colors", "text_colors"):
            for name, color in value.items():
                if not HEX_COLOR.match(color):
                    raise ValueError(f"[{section}.{key}].{name} must be #RRGGBB")
                getattr(target, key)[AgentState[name.upper()]] = color
            continue
        setattr(target, key, value)


def parse_icon(text: str, where: str, max_width: int) -> tuple[str, ...]:
    """An icon mask: rows of "#" and "." (spaces count as "."), padded to one width."""
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if bad := set("".join(lines)) - {"#", ".", " "}:
        raise ValueError(f"{where}.icon may only use '#', '.' and spaces, found {''.join(sorted(bad))!r}")
    if not lines or "#" not in "".join(lines):
        raise ValueError(f"{where}.icon has no lit pixels (#)")
    width = max(len(line) for line in lines)
    if width > max_width or len(lines) > ICON_MAX_ROWS:
        raise ValueError(f"{where}.icon is {width}x{len(lines)}; the most is {max_width}x{ICON_MAX_ROWS}")
    return tuple(line.replace(" ", ".").ljust(width, ".") for line in lines)


def _apply_projects(cfg: Config, projects: dict) -> None:
    for folder, table in projects.items():
        where = f'[projects."{folder}"]'
        if not isinstance(table, dict) or set(table) - {"icon"}:
            raise ValueError(f"{where} only supports the key 'icon'")
        if "icon" in table:
            # Not resolve(): sessions report their cwd as typed, symlinks and all.
            key = os.path.normpath(os.path.expanduser(folder))
            cfg.layout.icons[key] = parse_icon(str(table["icon"]), where, cfg.layout.tile_width)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    cfg = Config()
    if not path.exists():
        return cfg
    data = tomllib.loads(path.read_text())
    unknown = set(data) - {"busybar", "layout", "timing", "projects", "plugin"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    for section in ("busybar", "layout", "timing", "plugin"):
        if section in data:
            _apply(getattr(cfg, section), data[section], section)
    _apply_projects(cfg, data.get("projects", {}))  # after [layout], which sets tile_width
    if cfg.plugin.builtin not in BUILTIN_PLUGINS:
        raise ValueError(f"[plugin] builtin must be one of {', '.join(BUILTIN_PLUGINS)}")
    if cfg.plugin.interval_s < 1 or cfg.plugin.timeout_s <= 0:
        raise ValueError("[plugin] interval_s must be at least 1 and timeout_s above 0")
    return cfg
