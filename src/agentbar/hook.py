"""Hook-side forwarder: `agentbar-hook <source> [--resolve-pid]`.

Reads the harness's hook JSON on stdin and forwards it to the daemon over a
Unix socket. Runs once per hook event (including every tool call), so it is
stdlib-only, prints nothing, and always exits 0 - a missing daemon must never
slow down or break the harness.

Harness-agnostic: it forwards top-level scalar fields, plus the length of
each top-level list as `<key>_len`, and leaves all interpretation to the
adapter inside the daemon.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

from .paths import socket_path

MAX_STR = 512
CONNECT_TIMEOUT_S = 0.25
SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}


def scalars(payload: dict) -> dict:
    """Keep top-level scalars, and replace lists by their length (`<key>_len`).
    Drops bulky fields such as tool_input."""
    out: dict = {}
    for key, value in payload.items():
        if isinstance(value, str):
            out[key] = value[:MAX_STR]
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, list):
            out[f"{key}_len"] = len(value)
    return out


def parse_ps(stdout: str) -> dict[int, tuple[int, str]]:
    """`ps -A -o pid=,ppid=,comm=` -> {pid: (ppid, executable basename)}."""
    table: dict[int, tuple[int, str]] = {}
    for line in stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2].strip()).lstrip("-"))
    return table


def first_non_shell(table: dict[int, tuple[int, str]], start: int) -> int | None:
    pid = start
    for _ in range(32):
        entry = table.get(pid)
        if entry is None:
            return None
        ppid, name = entry
        if name not in SHELLS:
            return pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def harness_pid() -> int | None:
    """Nearest ancestor that is not a shell: the process that ran the hook.

    Costs one `ps` call, so it is only done when --resolve-pid is passed
    (once per prompt, not once per tool call).
    """
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,comm="],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return first_non_shell(parse_ps(result.stdout), os.getppid())


def send(data: bytes) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(CONNECT_TIMEOUT_S)
        sock.connect(str(socket_path()))
        sock.sendall(data)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    source = next((a for a in args if not a.startswith("-")), "unknown")
    try:
        raw = sys.stdin.buffer.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        message = {
            "v": 1,
            "type": "event",
            "source": source,
            "ts": time.time(),
            "pid": harness_pid() if "--resolve-pid" in args else None,
            "payload": scalars(payload),
        }
        send(json.dumps(message).encode() + b"\n")
    except Exception:  # noqa: BLE001 - never fail the harness
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
