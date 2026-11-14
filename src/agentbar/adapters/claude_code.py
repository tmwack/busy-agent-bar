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
  SubagentStart                           -> agent WORKING
  SubagentStop                            -> agent removed
  anything else (PreCompact, ...)         -> no change

Hooks fired inside a subagent carry agent_id; the registry applies their state
to that agent instead of the session. Stop with no background tasks in flight
clears any agents left over from a missed SubagentStop.

session_title (SessionStart and UserPromptSubmit, named sessions only) becomes
the session's title, which the tile label prefers over the cwd.
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
    common = dict(
        source=SOURCE,
        session_id=str(session_id),
        ts=ts,
        cwd=payload.get("cwd"),
        title=payload.get("session_title"),  # only set for named sessions (--name, /rename)
        pid=pid,
        agent_id=payload.get("agent_id") or None,
        agent_type=payload.get("agent_type") or None,
    )

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
        return (
            state(AgentState.NEEDS_INPUT, payload.get("notification_type"))
            if _needs_input_notification(payload)
            else touch
        )
    if name == "Stop":
        # background_tasks_len is absent on older versions: unknown, keep agents.
        return AgentEvent(
            kind=EventKind.STATE,
            state=AgentState.DONE,
            agents_idle=payload.get("background_tasks_len") == 0,
            **common,
        )
    if name == "SessionEnd":
        return AgentEvent(kind=EventKind.END, **common)
    if name == "SubagentStart" and common["agent_id"]:
        return state(AgentState.WORKING)
    if name == "SubagentStop" and common["agent_id"]:
        return AgentEvent(kind=EventKind.END, **common)
    return touch
