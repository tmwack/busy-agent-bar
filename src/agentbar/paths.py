"""Filesystem locations. Stdlib only: imported by the hook forwarder."""

from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agentbar"


def socket_path() -> Path:
    override = os.environ.get("AGENTBAR_SOCKET")
    return Path(override) if override else state_dir() / "agentbar.sock"


def config_path() -> Path:
    override = os.environ.get("AGENTBAR_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agentbar" / "config.toml"
