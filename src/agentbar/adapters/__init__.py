"""Harness adapters: native hook payload -> AgentEvent.

To add a harness: write a module with SOURCE and normalize(), register it
below, and point that harness's hooks at `agentbar-hook <SOURCE>`.
"""

from __future__ import annotations

from collections.abc import Callable

from ..model import AgentEvent
from . import claude_code

Normalizer = Callable[[dict, float, "int | None"], "AgentEvent | None"]

NORMALIZERS: dict[str, Normalizer] = {
    claude_code.SOURCE: claude_code.normalize,
}


def normalize(
    source: str, payload: dict, ts: float, pid: int | None
) -> AgentEvent | None:
    fn = NORMALIZERS.get(source)
    return fn(payload, ts, pid) if fn else None
