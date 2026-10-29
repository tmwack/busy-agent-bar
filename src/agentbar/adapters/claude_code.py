"""Claude Code hooks -> AgentEvent.

State mapping:
  SessionStart (startup/resume/clear)     -> IDLE
  SessionStart (compact)                  -> no change
  UserPromptSubmit                        -> WORKING
  PreToolUse                              -> WORKING (AskUserQuestion -> NEEDS_INPUT)
  PostToolUse / PostToolUseFailure        -> WORKING
  PermissionRequest                       -> NEEDS_INPUT
  Notification permission_prompt /
               elicitation_dialog         -> NEEDS_INPUT
  Notification (other, incl. idle_prompt) -> no change
  Stop                                    -> DONE
  SessionEnd                              -> session removed
  anything else (PreCompact, SubagentStop) -> no change
"""

from __future__ import annotations

from ..model import AgentEvent, AgentState, EventKind

SOURCE = "claude-code"

ASK_TOOLS = frozenset({"AskUserQuestion"})
NEEDS_INPUT_NOTIFICATIONS = frozenset({"permission_prompt", "elicitation_dialog"})


def _needs_input_notification(payload: dict) -> bool:
    kind = payload.get("notification_type")
    if kind is not None:
        return kind in NEEDS_INPUT_NOTIFICATIONS
    # Older versions without notification_type.
    return "permission" in str(payload.get("message") or "").lower()


def normalize(payload: dict, ts: float, pid: int | None) -> AgentEvent | None:
    session_id = payload.get("session_id")
    name = payload.get("hook_event_name")
    if not session_id or not name:
        return None

    tool = payload.get("tool_name")
    common = dict(source=SOURCE, session_id=str(session_id), ts=ts, cwd=payload.get("cwd"), pid=pid)

    def state(s: AgentState, detail: str | None = None) -> AgentEvent:
        return AgentEvent(kind=EventKind.STATE, state=s, detail=detail, **common)

    touch = AgentEvent(kind=EventKind.TOUCH, **common)

    if name == "SessionStart":
        return touch if payload.get("source") == "compact" else state(AgentState.IDLE)
    if name == "UserPromptSubmit":
        return state(AgentState.WORKING)
    if name == "PreToolUse":
        if tool in ASK_TOOLS:
            return state(AgentState.NEEDS_INPUT, tool)
        return state(AgentState.WORKING, tool)
    if name in ("PostToolUse", "PostToolUseFailure"):
        return state(AgentState.WORKING, tool)
    if name == "PermissionRequest":
        return state(AgentState.NEEDS_INPUT, tool)
    if name == "Notification":
        return state(AgentState.NEEDS_INPUT, payload.get("notification_type")) if _needs_input_notification(payload) else touch
    if name == "Stop":
        return state(AgentState.DONE)
    if name == "SessionEnd":
        return AgentEvent(kind=EventKind.END, **common)
    return touch
