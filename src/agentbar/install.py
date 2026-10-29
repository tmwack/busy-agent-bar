"""Install/uninstall Claude Code hooks and the launchd agent."""

from __future__ import annotations

import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

MARKER = "agentbar-hook"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
LAUNCHD_LABEL = "com.agentbar.daemon"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "agentbar.log"

# event -> (matcher or None, resolve the harness PID on this event)
CLAUDE_EVENTS: dict[str, tuple[str | None, bool]] = {
    "SessionStart": (None, True),
    "UserPromptSubmit": (None, True),
    "PreToolUse": ("*", False),
    "PostToolUse": ("*", False),
    "PostToolUseFailure": ("*", False),
    "PermissionRequest": ("*", False),
    "Notification": (None, False),
    "Stop": (None, False),
    "SessionEnd": (None, False),
}
HOOK_TIMEOUT_S = 5


def executable(name: str) -> Path:
    """Sibling of the running interpreter's scripts (uv tool / venv), else PATH."""
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return candidate
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"cannot find {name}; is agentbar installed?")
    return Path(found)


def _strip_ours(hooks: dict) -> dict:
    cleaned: dict = {}
    for event, groups in hooks.items():
        kept_groups = []
        for group in groups:
            inner = [
                h
                for h in group.get("hooks", [])
                if MARKER not in str(h.get("command", ""))
            ]
            if inner:
                kept_groups.append({**group, "hooks": inner})
        if kept_groups:
            cleaned[event] = kept_groups
    return cleaned


def merge_hooks(settings: dict, hook_exe: Path) -> dict:
    hooks = _strip_ours(settings.get("hooks", {}))
    for event, (matcher, resolve_pid) in CLAUDE_EVENTS.items():
        command = f"{shlex.quote(str(hook_exe))} claude-code" + (
            " --resolve-pid" if resolve_pid else ""
        )
        group: dict = {
            "hooks": [
                {"type": "command", "command": command, "timeout": HOOK_TIMEOUT_S}
            ]
        }
        if matcher is not None:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)
    return {**settings, "hooks": hooks}


def remove_hooks(settings: dict) -> dict:
    hooks = _strip_ours(settings.get("hooks", {}))
    out = {k: v for k, v in settings.items() if k != "hooks"}
    if hooks:
        out["hooks"] = hooks
    return out


def _rewrite(path: Path, transform) -> Path | None:
    settings = json.loads(path.read_text()) if path.exists() else {}
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.agentbar-backup-{int(time.time())}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(transform(settings), indent=2) + "\n")
    os.replace(tmp, path)
    return backup


def install_hooks(settings_path: Path = CLAUDE_SETTINGS) -> Path | None:
    hook_exe = executable("agentbar-hook")
    return _rewrite(settings_path, lambda s: merge_hooks(s, hook_exe))


def uninstall_hooks(settings_path: Path = CLAUDE_SETTINGS) -> Path | None:
    if not settings_path.exists():
        return None
    return _rewrite(settings_path, remove_hooks)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install_agent() -> None:
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [str(executable("agentbar")), "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    LAUNCHD_PLIST.write_bytes(plistlib.dumps(plist))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LAUNCHD_LABEL}")
    result = _launchctl("bootstrap", domain, str(LAUNCHD_PLIST))
    if result.returncode != 0:
        raise SystemExit(f"launchctl bootstrap failed: {result.stderr.strip()}")


def uninstall_agent() -> None:
    _launchctl("bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
    LAUNCHD_PLIST.unlink(missing_ok=True)
