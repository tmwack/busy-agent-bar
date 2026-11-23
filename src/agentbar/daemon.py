"""Long-running daemon: Unix-socket event intake + render loop."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import signal
import socket
import time
from datetime import datetime
from pathlib import Path

from . import adapters, demo, layout, plugin, usage
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
        self._demo: Registry | None = None  # rendered instead of the real registry while a demo plays
        self._plugin_elements: dict[str, dict] = {}  # the plugin area's latest drawing
        self.plugin_status: dict | None = None
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
        plugin_task = asyncio.ensure_future(self._run_plugin())
        try:
            async with server:
                await self._render_loop()
        finally:
            plugin_task.cancel()
            await self.sink.reset()
            path.unlink(missing_ok=True)

    async def _run_plugin(self) -> None:
        """Keep the plugin area's drawing up to date for the render loop.

        With no command configured this is a built-in: the clock (redrawn as each minute
        starts) or today's token count (every interval_s). A command replaces it and runs
        every interval_s. On failure (exit status,
        timeout, unusable output) the area shows an amber "!" and the error is logged and
        reported by `agentbar status`.
        """
        cfg = self.cfg.plugin
        width = layout.region_x(self.cfg.layout)
        if not cfg.enabled:
            return
        if width < 1:
            log.warning("plugin disabled: the tiles leave no columns on the left ([layout] x)")
            return
        name = cfg.command or f"built-in {cfg.builtin}"
        tokens = usage.TokenCounter() if not cfg.command and cfg.builtin == "tokens" else None
        log.info("plugin: %s in a %dx%d area", name, width, plugin.HEIGHT)
        while not self._stop.is_set():
            started = time.time()
            try:
                if cfg.command:
                    output = await self._plugin_output(cfg.command, cfg.timeout_s)
                elif tokens is not None:
                    # A thread: the first read of the day walks every transcript.
                    output = plugin.tokens_output(await asyncio.to_thread(tokens.update), width)
                else:
                    output = plugin.clock_output(datetime.now(), width)
                elements = plugin.parse(output, width)
                error = None
            except (plugin.PluginError, OSError) as exc:
                elements, error = plugin.error_mark(width), str(exc)
            except Exception as exc:  # untrusted output must never stop the loop
                log.exception("plugin output handling failed")
                elements, error = plugin.error_mark(width), f"internal error: {exc}"
            if error != (self.plugin_status or {}).get("error"):
                if error:
                    log.warning("plugin failed: %s", error)
                else:
                    log.info("plugin ok")
            self.plugin_status = {"command": name, "last_run": started, "error": error}
            self._plugin_elements = {e["id"]: e for e in elements}
            self._wake.set()
            # The clock wakes just after the minute turns; the others run every interval_s.
            clock = datetime.now()
            on_the_minute = not cfg.command and cfg.builtin == "clock"
            wait = 60.05 - clock.second - clock.microsecond / 1e6 if on_the_minute else cfg.interval_s
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), wait)

    @staticmethod
    async def _plugin_output(command: str, timeout_s: float) -> str:
        proc = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # its own process group, so a timeout kills its children too
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            raise plugin.PluginError(f"timed out after {timeout_s:g} s") from None
        if proc.returncode != 0:
            detail = err.decode(errors="replace").strip().splitlines()
            raise plugin.PluginError(f"exit status {proc.returncode}" + (f": {detail[-1][:200]}" if detail else ""))
        return out.decode(errors="replace")

    async def _run_demo(self, msg: dict, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Play demo scenes in place of the real sessions, streaming captions to the client.

        Real events keep updating self.registry meanwhile; its tiles come back when the
        demo ends or the client disconnects (Ctrl-C).
        """

        def reply(obj: dict) -> None:
            writer.write(json.dumps(obj).encode() + b"\n")

        scenes = list(msg.get("scenes") or demo.SCENES)
        unknown = [s for s in scenes if s not in demo.SCENES]
        if self._demo is not None or unknown:
            reply({"error": "a demo is already running" if self._demo is not None else f"unknown scene: {unknown[0]}"})
            await writer.drain()
            return
        t = self.cfg.timing
        self._demo = Registry(t.done_decay_s, t.session_ttl_s, is_alive=lambda _: True, agent_pulse_s=t.agent_pulse_s)
        started = time.monotonic()

        async def on_step(scene: str, step: demo.Step) -> None:
            self._wake.set()
            if step.caption:
                reply({"t": round(time.monotonic() - started, 1), "scene": scene, "caption": step.caption})
                await writer.drain()

        player = asyncio.ensure_future(
            demo.play(
                self._demo,
                scenes,
                loop=bool(msg.get("loop")),
                on_step=on_step,
                time_scale=float(msg.get("time_scale") or 1.0),
            )
        )
        client_gone = asyncio.ensure_future(reader.read())  # EOF once the client goes away
        log.info("demo started: %s%s", ", ".join(scenes), " (loop)" if msg.get("loop") else "")
        try:
            await asyncio.wait({player, client_gone}, return_when=asyncio.FIRST_COMPLETED)
            if player.done() and player.exception() is None:
                reply({"done": True})
                await writer.drain()
        finally:
            player.cancel()
            client_gone.cancel()
            self._demo = None
            self._wake.set()
            log.info("demo ended")

    def status(self) -> dict:
        return {
            "demo": self._demo is not None,
            "plugin": self.plugin_status,
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
            if msg.get("type") == "demo":
                await self._run_demo(msg, reader, writer)
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
        except (TimeoutError, ValueError, TypeError, AttributeError, ConnectionError) as exc:
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
            self.registry.tick(now)  # real sessions keep updating while a demo plays
            if self._demo is not None:
                self._demo.tick(now)
            sessions = (self._demo if self._demo is not None else self.registry).sessions()
            mono = time.monotonic()
            if mono >= next_refresh:
                self.sink.invalidate()
                next_refresh = mono + timing.refresh_s
            # One frame clock: every animation steps on multiples of its period counted
            # from the same origin, so changes that fall on the same instant go out in
            # one draw request.
            blink_on = int(mono / half) % 2 == 0
            shimmer_phase = int(mono / step)  # frame count; layout takes each animation's cycle
            desired = layout.render(sessions, lay, blink_on, shimmer_phase, now, timing.agent_pulse_s)
            desired.update(self._plugin_elements)  # the plugin keeps showing during a demo
            await self.sink.apply(desired)
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
