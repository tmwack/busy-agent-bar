"""Long-running daemon: Unix-socket event intake + render loop."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import socket
import time
from pathlib import Path

from . import adapters, layout
from .config import Config
from .paths import socket_path
from .registry import Registry

log = logging.getLogger(__name__)


def claim_socket(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        return
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(str(path))
        except OSError:
            path.unlink()  # stale socket from a dead daemon
            return
    raise SystemExit(f"agentbar daemon already running on {path}")


FRAME_SLACK_S = 0.01  # wake just after a frame boundary, never just before it


def next_boundary(mono: float, period: float) -> float:
    """Seconds until just after the next multiple of period on the monotonic clock."""
    return (int(mono / period) + 1) * period - mono + FRAME_SLACK_S


class Daemon:
    def __init__(self, cfg: Config, sink) -> None:
        self.cfg = cfg
        self.sink = sink
        self.registry = Registry(
            cfg.timing.done_decay_s, cfg.timing.session_ttl_s, agent_pulse_s=cfg.timing.agent_pulse_s
        )
        layout.region_x(cfg.layout)  # fail fast on a layout that does not fit
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self, path: Path | None = None) -> None:
        path = path or socket_path()
        claim_socket(path)
        server = await asyncio.start_unix_server(self._handle, path=str(path))
        os.chmod(path, 0o600)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop)
        await self.sink.reset()
        log.info("listening on %s", path)
        try:
            async with server:
                await self._render_loop()
        finally:
            await self.sink.reset()
            path.unlink(missing_ok=True)

    def status(self) -> dict:
        return {
            "blocked": self.sink.blocked,
            "reachable": self.sink.reachable,
            "sessions": [
                {
                    "source": s.source,
                    "session_id": s.session_id,
                    "cwd": s.cwd,
                    "title": s.title,
                    "state": s.state.name,
                    "state_since": s.state_since,
                    "pid": s.pid,
                    "detail": s.detail,
                    "active": s.active,
                    "agents": [
                        {"agent_id": a.agent_id, "agent_type": a.agent_type, "state": a.state.name}
                        for a in s.agents.values()
                    ],
                }
                for s in self.registry.sessions()
            ],
        }

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            msg = json.loads(line)
            if msg.get("type") == "status":
                writer.write(json.dumps(self.status()).encode() + b"\n")
                await writer.drain()
                return
            if msg.get("type") == "screen":
                rgb = await self.sink.screen()
                reply = {"rgb": base64.b64encode(rgb).decode() if rgb else None}
                writer.write(json.dumps(reply).encode() + b"\n")
                await writer.drain()
                return
            ev = adapters.normalize(
                str(msg.get("source", "")),
                msg.get("payload") or {},
                float(msg.get("ts") or time.time()),
                msg.get("pid"),
            )
            if ev is not None and self.registry.apply(ev):
                self._wake.set()
        except (TimeoutError, ValueError, TypeError, AttributeError) as exc:
            log.debug("dropped message: %s", exc)
        finally:
            writer.close()

    async def _render_loop(self) -> None:
        timing, lay = self.cfg.timing, self.cfg.layout
        half = timing.blink_period_s / 2
        step = timing.shimmer_step_s
        pulse_half = timing.agent_pulse_s / 2
        next_refresh = time.monotonic() + timing.refresh_s
        while not self._stop.is_set():
            self._wake.clear()
            now = time.time()
            self.registry.tick(now)
            sessions = self.registry.sessions()
            mono = time.monotonic()
            if mono >= next_refresh:
                self.sink.invalidate()
                next_refresh = mono + timing.refresh_s
            # One frame clock: every animation steps on multiples of its period counted
            # from the same origin, so changes that fall on the same instant go out in
            # one draw request.
            blink_on = int(mono / half) % 2 == 0
            shimmer_phase = int(mono / step)  # frame count; layout takes each animation's cycle
            await self.sink.apply(layout.render(sessions, lay, blink_on, shimmer_phase, now, timing.agent_pulse_s))
            periods = [
                p
                for p, active in (
                    (half, layout.blinking(sessions, lay)),
                    (step, layout.shimmering(sessions, lay)),
                    (pulse_half, layout.pulsing(sessions, lay)),
                )
                if active
            ]
            timeout = min([next_boundary(mono, p) for p in periods], default=1.0)
            await self._sleep(timeout)

    async def _sleep(self, timeout: float) -> None:
        waiters = {asyncio.ensure_future(self._wake.wait()), asyncio.ensure_future(self._stop.wait())}
        _, pending = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
