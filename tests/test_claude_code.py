from agentbar.adapters import normalize
from agentbar.model import AgentState, EventKind


def ev(name, **extra):
    return normalize("claude-code", {"session_id": "s1", "cwd": "/w/proj", "hook_event_name": name, **extra}, 1.0, None)


def test_state_mapping():
    assert ev("UserPromptSubmit").state is AgentState.WORKING
    assert ev("PreToolUse", tool_name="Bash").state is AgentState.WORKING
    assert ev("PreToolUse", tool_name="AskUserQuestion").state is AgentState.NEEDS_INPUT
    assert ev("PostToolUse", tool_name="Bash").state is AgentState.WORKING
    assert ev("PermissionRequest", tool_name="Bash").state is AgentState.NEEDS_INPUT
    assert ev("Notification", notification_type="permission_prompt").state is AgentState.NEEDS_INPUT
    assert ev("Stop").state is AgentState.DONE
    assert ev("SessionStart", source="startup").state is AgentState.IDLE
    assert ev("SessionEnd").kind is EventKind.END


def test_non_state_events_touch():
    assert ev("Notification", notification_type="idle_prompt").kind is EventKind.TOUCH
    assert ev("SessionStart", source="compact").kind is EventKind.TOUCH
    assert ev("SubagentStop").kind is EventKind.TOUCH


def test_session_title_passed_through():
    assert ev("UserPromptSubmit", session_title="Fix auth bug").title == "Fix auth bug"
    assert ev("Stop").title is None


def test_legacy_notification_without_type():
    assert ev("Notification", message="Claude needs your permission to use Bash").state is AgentState.NEEDS_INPUT


def test_rejects_incomplete_and_unknown_source():
    assert normalize("claude-code", {"hook_event_name": "Stop"}, 1.0, None) is None
    assert normalize("other", {"session_id": "s", "hook_event_name": "Stop"}, 1.0, None) is None
