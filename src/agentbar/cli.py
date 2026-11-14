"""agentbar CLI: run | status | install | uninstall."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
import time
from pathlib import Path

from . import install
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


def _status(_: argparse.Namespace) -> int:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(str(socket_path()))
            sock.sendall(json.dumps({"v": 1, "type": "status"}).encode() + b"\n")
            data = sock.makefile("rb").readline()
    except OSError as exc:
        print(f"daemon not reachable at {socket_path()}: {exc}", file=sys.stderr)
        return 1
    status = json.loads(data)
    print(f"bar: {'unreachable' if not status['reachable'] else 'yielding to BUSY' if status['blocked'] else 'ok'}")
    now = time.time()
    for s in status["sessions"]:
        age = int(now - s["state_since"])
        where = s["cwd"] or "-"
        if s.get("title"):
            where = f'"{s["title"]}" {where}'
        print(f"{s['state']:<12} {age:>5}s  {where}  ({s['source']} {s['session_id'][:8]} pid={s['pid']})")
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
