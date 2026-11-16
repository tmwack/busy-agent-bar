"""agentbar CLI: run | status | screen | demo | install | uninstall."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import socket
import sys
import time
from pathlib import Path

from . import demo, install
from .paths import socket_path


def _run(args: argparse.Namespace) -> int:
    from .config import load
    from .daemon import Daemon
    from .sink import BusyBarSink, LogSink

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        # busylib and its HTTP client each log every request at INFO.
        for name in ("busylib", "httpx", "httpx2"):
            logging.getLogger(name).setLevel(logging.WARNING)
    cfg = load(args.config)
    sink = LogSink() if args.dry_run else BusyBarSink(cfg.busybar, cfg.timing.busy_retry_s)
    asyncio.run(Daemon(cfg, sink).run())
    return 0


def _ask(kind: str) -> dict | None:
    """Send one request to the daemon and return its reply."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(socket_path()))
            sock.sendall(json.dumps({"v": 1, "type": kind}).encode() + b"\n")
            return json.loads(sock.makefile("rb").readline())
    except OSError as exc:
        print(f"daemon not reachable at {socket_path()}: {exc}", file=sys.stderr)
        return None


def pixel_symbol(r: int, g: int, b: int) -> str:
    """Rough colour of one framebuffer pixel, as a terminal block."""
    if max(r, g, b) < 24:
        return "⬛"
    if r > 2 * b and g > 2 * b and r >= g:
        return "🟨" if r > 128 else "🟫"  # amber; dim amber is the blink's off phase
    if g > 2 * r and g >= b:
        return "🟩" if g >= 150 else "🟢"  # green, dim green
    if b > r and b >= g:
        return "🟦"  # cyan / steel blue
    return "⬜"


def _screen(args: argparse.Namespace) -> int:
    for i in range(args.frames):
        reply = _ask("screen")
        if reply is None:
            return 1
        if not reply.get("rgb"):
            print("no capture (bar unreachable, or the daemon runs with --dry-run)", file=sys.stderr)
            return 1
        rgb = base64.b64decode(reply["rgb"])
        if args.frames > 1:
            print(f"capture {i + 1}")
        for y in range(16):
            print("".join(pixel_symbol(*rgb[(y * 72 + x) * 3 : (y * 72 + x) * 3 + 3]) for x in range(72)))
        if i + 1 < args.frames:
            time.sleep(args.interval)
    return 0


def _demo(args: argparse.Namespace) -> int:
    scenes = args.scene or list(demo.SCENES)
    request = {"v": 1, "type": "demo", "scenes": scenes, "loop": args.loop}
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(socket_path()))
    except OSError as exc:
        print(f"daemon not reachable at {socket_path()}: {exc}", file=sys.stderr)
        return 1
    length = f"{demo.duration(scenes):.0f} s" + (", looping" if args.loop else "")
    print(f"demo: {', '.join(scenes)} ({length}); Ctrl-C stops it and restores the bar")
    scene = None
    with sock:
        sock.sendall(json.dumps(request).encode() + b"\n")
        try:
            for line in sock.makefile("rb"):
                reply = json.loads(line)
                if "error" in reply:
                    print(f"demo: {reply['error']}", file=sys.stderr)
                    return 1
                if reply.get("done"):
                    print("demo finished, bar restored")
                    return 0
                if reply["scene"] != scene:
                    scene = reply["scene"]
                    print(f"-- {scene}")
                minutes, seconds = divmod(int(reply["t"]), 60)
                print(f"[{minutes}:{seconds:02}] {reply['caption']}")
        except KeyboardInterrupt:
            print("\ndemo stopped, bar restored")
            return 0
    print("daemon closed the connection", file=sys.stderr)
    return 1


def _status(_: argparse.Namespace) -> int:
    status = _ask("status")
    if status is None:
        return 1
    print(f"bar: {'unreachable' if not status['reachable'] else 'yielding to BUSY' if status['blocked'] else 'ok'}")
    if status.get("demo"):
        print("demo: running (real sessions are hidden until it ends)")
    now = time.time()
    for s in status["sessions"]:
        age = int(now - s["state_since"])
        where = s["cwd"] or "-"
        if s.get("title"):
            where = f'"{s["title"]}" {where}'
        hidden = "" if s.get("active", True) else "  [hidden until its first prompt]"
        print(f"{s['state']:<12} {age:>5}s  {where}  ({s['source']} {s['session_id'][:8]} pid={s['pid']}){hidden}")
        for a in s.get("agents", []):
            print(f"  └ {a['state']:<12} {a['agent_type'] or 'agent'} {a['agent_id'][:12]}")
    if not status["sessions"]:
        print("no sessions")
    return 0


def _install(args: argparse.Namespace) -> int:
    backup = install.install_hooks(args.settings)
    print(f"hooks installed in {args.settings}" + (f" (backup: {backup})" if backup else ""))
    if not args.no_agent:
        install.install_agent()
        print(f"launchd agent loaded ({install.LAUNCHD_LABEL}); log: {install.LOG_PATH}")
    return 0


def _uninstall(args: argparse.Namespace) -> int:
    backup = install.uninstall_hooks(args.settings)
    print(f"hooks removed from {args.settings}" + (f" (backup: {backup})" if backup else ""))
    if not args.no_agent:
        install.uninstall_agent()
        print("launchd agent removed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentbar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the daemon in the foreground")
    run.add_argument("--dry-run", action="store_true", help="log renders instead of drawing")
    run.add_argument("--config", type=Path, default=None)
    run.add_argument("-v", "--verbose", action="store_true")
    run.set_defaults(fn=_run)

    sub.add_parser("status", help="show sessions tracked by the daemon").set_defaults(fn=_status)

    screen = sub.add_parser("screen", help="capture the bar's front display through the daemon")
    screen.add_argument("--frames", type=int, default=1, help="number of captures")
    screen.add_argument("--interval", type=float, default=1.0, help="seconds between captures")
    screen.set_defaults(fn=_screen)

    play = sub.add_parser("demo", help="play a scripted demo on the bar; real sessions return afterwards")
    play.add_argument(
        "--scene",
        action="append",
        choices=list(demo.SCENES),
        help="scene to play (repeatable; default: all, in order)",
    )
    play.add_argument("--loop", action="store_true", help="repeat until Ctrl-C")
    play.set_defaults(fn=_demo)

    for name, fn, text in (
        ("install", _install, "add Claude Code hooks and the launchd agent"),
        ("uninstall", _uninstall, "remove Claude Code hooks and the launchd agent"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--settings", type=Path, default=install.CLAUDE_SETTINGS)
        p.add_argument("--no-agent", action="store_true", help="hooks only; skip launchd")
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
