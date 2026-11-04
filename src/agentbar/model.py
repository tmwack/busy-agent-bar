"""Harness-agnostic session model. Adapters translate native events into AgentEvent."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AgentState(enum.IntEnum):
    """Session state. The integer value is the priority used when there are
    more sessions than tiles: higher values win a tile first."""

    IDLE = 0
    DONE = 1
    WORKING = 2
    NEEDS_INPUT = 3


class EventKind(enum.Enum):
    STATE = "state"  # set the session's state
    TOUCH = "touch"  # session is alive; no state change
    END = "end"  # session is gone


@dataclass(frozen=True)
class AgentEvent:
    source: str  # harness id, e.g. "claude-code"
    session_id: str
    kind: EventKind
    ts: float  # unix seconds, stamped by the forwarder
    state: AgentState | None = None
    cwd: str | None = None
    title: str | None = None  # user-set session name, if the harness reports one
    pid: int | None = None  # harness process, for liveness checks
    detail: str | None = None  # e.g. tool name


@dataclass
class Session:
    source: str
    session_id: str
    first_seen: float
    last_event: float
    state: AgentState = AgentState.IDLE
    state_since: float = 0.0  # when the current state was entered
    last_state_ts: float = 0.0  # ts of the newest applied STATE event (ordering guard)
    cwd: str | None = None
    title: str | None = None
    pid: int | None = None
    detail: str | None = None
