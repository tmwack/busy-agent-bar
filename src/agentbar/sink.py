"""Output sinks. BusyBarSink diffs desired elements against what it believes
is on the display and sends only changes."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Callable

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarAPIError, BusyBarError
from busylib.types import DisplayElements

from . import layout, plugin
from .config import BusyBarConfig

log = logging.getLogger(__name__)


class BusyBarSink:
    def __init__(
        self,
        cfg: BusyBarConfig,
        retry_s: float,
        client: object | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.retry_s = retry_s
        self.client = client or AsyncBusyBar(cfg.host, token=cfg.token or None, timeout=cfg.timeout_s, max_retries=0)
        self._clock = clock
        self._drawn: dict[str, dict] = {}
        self._blocked_until = 0.0
        self.blocked = False  # True while a BUSY session outranks us
        self.reachable = True

    def invalidate(self) -> None:
        """Forget what is on screen; the next apply re-sends everything."""
        self._drawn = {}

    async def reset(self) -> None:
        """Remove everything this application drew (startup / shutdown)."""
        self._drawn = {}
        try:
            await self.client.display_clear(application_name=self.cfg.application_name)
        except BusyBarError as exc:
            log.warning("clear failed: %s", exc)

    async def screen(self) -> bytes | None:
        """What the front display shows right now: 72x16 RGB, 3 bytes per pixel."""
        try:
            return await self.client.screen(0)
        except BusyBarError as exc:
            log.warning("screen capture failed: %s", exc)
            return None

    async def _draw(self, elements: list[dict]) -> None:
        """POST elements. busylib's display_draw validates every element against its own
        types and rejects the firmware's "xpmbitmap" (icons), so draws with bitmaps
        validate the rest the same way and go through the raw api_request instead."""
        request = {"application_name": self.cfg.application_name, "priority": self.cfg.priority}
        bitmaps = [e for e in elements if e["type"] == "xpmbitmap"]
        if not bitmaps:
            await self.client.display_draw({**request, "elements": elements})
            return
        others = [e for e in elements if e["type"] != "xpmbitmap"]
        if others:
            payload = DisplayElements.model_validate({**request, "elements": others}).model_dump(exclude_none=True)
        else:
            payload = dict(request, elements=[])
        payload["elements"] = [*payload["elements"], *bitmaps]
        await self.client.api_request("POST", "/api/display/draw", json_payload=payload)

    async def apply(self, desired: dict[str, dict]) -> None:
        now = self._clock()
        if now < self._blocked_until:
            return
        app = self.cfg.application_name
        removed = sorted(self._drawn.keys() - desired.keys())
        changed = [e for i, e in desired.items() if self._drawn.get(i) != e]
        if not removed and not changed:
            return
        try:
            if removed:
                await self.client.display_clear(element_ids=removed, application_name=app)
                for i in removed:
                    self._drawn.pop(i, None)
            if changed:
                await self._draw(changed)
                self._drawn.update({e["id"]: e for e in changed})
            if self.blocked or not self.reachable:
                log.info("drawing resumed")
            self.blocked = False
            self.reachable = True
        except BusyBarAPIError as exc:
            self._drawn = {}
            self._blocked_until = now + self.retry_s
            if exc.status_code == 409:
                # A higher-priority drawing (BUSY session) is active: yield.
                if not self.blocked:
                    log.info("bar busy (409), hiding until it ends")
                self.blocked = True
                # Hide anything drawn before the session started.
                with contextlib.suppress(BusyBarError):
                    await self.client.display_clear(application_name=app)
            else:
                log.warning("draw rejected: %s", exc)
        except BusyBarError as exc:
            self._drawn = {}
            self._blocked_until = now + self.retry_s
            if self.reachable:
                log.warning("bar unreachable: %s", exc)
            self.reachable = False


class LogSink:
    """--dry-run: log what would be drawn instead of talking to a bar."""

    blocked = False
    reachable = True

    def __init__(self) -> None:
        self._last: dict[str, dict] | None = None

    def invalidate(self) -> None:
        pass

    async def reset(self) -> None:
        self._last = None

    async def screen(self) -> bytes | None:
        return None

    async def apply(self, desired: dict[str, dict]) -> None:
        if desired == self._last:
            return
        self._last = desired
        # Element ids are 100*(slot+1) + offset; see layout.py.
        tiles: dict[int, dict] = {}
        area = [e for i, e in desired.items() if int(i) >= plugin.FIRST_ID]
        for i, e in sorted(desired.items(), key=lambda kv: int(kv[0])):
            if int(i) >= plugin.FIRST_ID:
                continue
            tile = tiles.setdefault(int(i) // 100, {"agents": []})
            offset = int(i) % 100
            if e["type"] == "text":
                tile.update(text=e["text"], color=e["color"], x=e["x"])
            elif e["type"] == "xpmbitmap":
                rows = e["data"].splitlines()
                tile.update(icon=rows[4:], color=rows[3].split()[-1], x=e["x"])
            elif offset == 0:
                tile["bar"] = e["fill_colors"]
            elif offset == layout.SEGMENT:
                tile["segment_x"] = e["x"]
            elif layout.AGENT <= offset < layout.AGENT_PIXEL:
                tile["agents"].append(e["fill_colors"][0])
        if area:
            tiles[0] = {"plugin": [e.get("text", e["type"]) for e in area]}
        log.info("render %s", json.dumps(list(tiles.values())))
