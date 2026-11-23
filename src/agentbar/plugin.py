"""Plugin area: the columns left of the tiles, fed by one user command.

The bar shows one application at a time; a drawing under another application name would
wipe the tiles. So agentbar runs the plugin command itself and draws its output as part
of its own drawing. This module is pure: command output -> positioned draw elements.

Output contract: either one line of plain text, or JSON {"elements": [...]} with up to
MAX_ELEMENTS elements of type text, rectangle or xpmbitmap, in coordinates local to the
area (x 0..width-1, y 0..15). agentbar assigns ids and z_index; other fields are dropped.
"""

from __future__ import annotations

import json
from datetime import datetime

from busylib.exceptions import BusyBarError
from busylib.types import DisplayElements

FIRST_ID = 900  # above every tile id (100..399)
MAX_ELEMENTS = 20
HEIGHT = 16
TEXT_COLOR = "#FFFFFF"
ERROR_COLOR = "#FFC000"  # the needs-input amber
BUILTIN_CLOCK = "built-in clock"  # the default plugin when [plugin] sets no command
CLOCK_COLOR = "#909090"  # dimmer than white: the tiles, not the clock, should catch the eye
CLOCK_LINE_COLOR = "#385868"  # the idle bar's dim steel blue

FIELDS = {
    "text": {"x", "y", "text", "font", "color", "width"},
    "rectangle": {"x", "y", "width", "height", "fill", "fill_colors", "border_width", "border_color", "radius"},
    "xpmbitmap": {"x", "y", "data", "opacity"},
}


class PluginError(ValueError):
    """The plugin's output can't be drawn."""


def parse(output: str, width: int) -> list[dict]:
    """Plugin stdout -> elements positioned in an area `width` columns wide."""
    text = output.strip()
    if not text:
        raise PluginError("no output")
    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginError(f"bad JSON: {exc}") from exc
        items = doc.get("elements") if isinstance(doc, dict) else None
        if not isinstance(items, list) or not items:
            raise PluginError('JSON output needs a non-empty "elements" list')
    else:
        items = [{"type": "text", "x": 0, "y": 4, "text": text.splitlines()[0]}]
    if len(items) > MAX_ELEMENTS:
        raise PluginError(f"{len(items)} elements; the most is {MAX_ELEMENTS}")
    elements = [_place(item, width, str(FIRST_ID + i)) for i, item in enumerate(items)]
    others = [e for e in elements if e["type"] != "xpmbitmap"]
    if others:  # catch bad colours or fonts here, not as a failed draw that hides the tiles too
        try:
            DisplayElements.model_validate({"application_name": "plugin", "elements": others})
        except (BusyBarError, ValueError) as exc:  # busylib wraps pydantic's ValidationError
            cause = exc.__cause__ if hasattr(exc.__cause__, "errors") else exc
            errors = cause.errors() if hasattr(cause, "errors") else [{"msg": str(exc)}]
            raise PluginError(f"invalid element: {errors[0]['msg']}") from exc
    return elements


def _int(item: dict, key: str, default: int | None = None) -> int:
    value = item.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PluginError(f"{item.get('type')}: {key} must be an integer")
    return value


def _place(item: object, width: int, element_id: str) -> dict:
    if not isinstance(item, dict) or item.get("type") not in FIELDS:
        raise PluginError(f"element types are {', '.join(FIELDS)}")
    kind = item["type"]
    e = {k: v for k, v in item.items() if k in FIELDS[kind]}
    x, y = _int(item, "x", 0), _int(item, "y", 0)
    if not (0 <= x < width and 0 <= y < HEIGHT):
        raise PluginError(f"{kind} at ({x}, {y}) is outside the {width}x{HEIGHT} area")
    e.update(id=element_id, z_index=int(element_id), type=kind, display="front", x=x, y=y)
    if kind == "text":
        if not isinstance(item.get("text"), str):
            raise PluginError("text: text must be a string")
        e.setdefault("font", "small")
        e.setdefault("color", TEXT_COLOR)
        e["width"] = min(_int(item, "width", width - x), width - x)  # clip at the area's edge
    elif kind == "rectangle":
        e["width"] = min(_int(item, "width"), width - x)
        e["height"] = min(_int(item, "height"), HEIGHT - y)
        e.setdefault("border_width", 0)
        if e.get("fill", "solid") == "solid":
            # Always a gradient: the firmware's solid fill keeps an earlier gradient (see
            # layout.bar_elements), and a plugin may switch between the two.
            color = (e.get("fill_colors") or [TEXT_COLOR])[0]
            e.update(fill="gradient_h", fill_colors=[color, color])
    else:
        data = item.get("data")
        if not isinstance(data, str):
            raise PluginError("xpmbitmap: data must be XPM2 text")
        try:
            w, h = (int(n) for n in data.splitlines()[1].split()[:2])
        except (IndexError, ValueError) as exc:
            raise PluginError("xpmbitmap: data must start with '! XPM2' and a 'width height ...' line") from exc
        if x + w > width or y + h > HEIGHT:
            raise PluginError(f"xpmbitmap {w}x{h} at ({x}, {y}) doesn't fit the {width}x{HEIGHT} area")
    return e


def clock_output(now: datetime, width: int) -> str:
    """The built-in plugin, in the same output contract as a command: the time, and a
    line along the bottom that fills as the hour passes (examples/clock.sh is the same
    clock as a command plugin)."""
    fill = now.minute * width // 60 + 1  # 1..width columns
    elements = [
        {"type": "text", "x": 0, "y": 3, "text": f"{now.hour}:{now.minute:02d}", "color": CLOCK_COLOR},
        {"type": "rectangle", "x": 0, "y": 14, "width": fill, "height": 1, "fill_colors": [CLOCK_LINE_COLOR]},
    ]
    return json.dumps({"elements": elements})


def compact(n: int) -> str:
    """A count in at most 4 characters, to fit 16 px in the small font: 812, 8.1k, 812k, 5.8M, 12M."""
    for size, suffix in ((10**9, "B"), (10**6, "M"), (10**3, "k")):
        if n >= size:
            value = n / size  # truncated, not rounded: never overstates, and 9999 stays "9.9k"
            return f"{int(value * 10) / 10:.1f}{suffix}" if value < 10 else f"{int(value)}{suffix}"
    return str(n)


def tokens_output(total: int, width: int) -> str:
    """The built-in tokens plugin: today's Claude Code tokens, all sessions together."""
    return json.dumps({"elements": [{"type": "text", "x": 0, "y": 3, "text": compact(total), "color": CLOCK_COLOR}]})


def error_mark(width: int) -> list[dict]:
    """A small amber "!" in the middle of the area."""
    x = width // 2

    def bar(i: int, y: int, h: int) -> dict:
        element_id = str(FIRST_ID + i)
        return {
            "id": element_id,
            "z_index": int(element_id),
            "type": "rectangle",
            "display": "front",
            "x": x,
            "y": y,
            "width": 1,
            "height": h,
            "fill": "gradient_h",
            "fill_colors": [ERROR_COLOR, ERROR_COLOR],
            "border_width": 0,
        }

    return [bar(0, 4, 5), bar(1, 10, 1)]
