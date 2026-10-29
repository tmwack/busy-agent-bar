from pathlib import Path

from agentbar.install import CLAUDE_EVENTS, merge_hooks, remove_hooks

OTHER = {"type": "command", "command": "afplay ding.aiff"}


def test_merge_is_idempotent_and_preserves_other_hooks():
    settings = {"model": "opus", "hooks": {"Stop": [{"hooks": [OTHER]}]}}
    once = merge_hooks(settings, Path("/bin/agentbar-hook"))
    twice = merge_hooks(once, Path("/bin/agentbar-hook"))
    assert once == twice
    assert set(CLAUDE_EVENTS) <= set(twice["hooks"])
    assert twice["hooks"]["Stop"][0]["hooks"] == [OTHER]
    assert twice["model"] == "opus"
    pre = twice["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "*" and "--resolve-pid" not in pre["hooks"][0]["command"]
    assert (
        "--resolve-pid" in twice["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    )


def test_remove_leaves_only_other_hooks():
    merged = merge_hooks(
        {"hooks": {"Stop": [{"hooks": [OTHER]}]}}, Path("/bin/agentbar-hook")
    )
    assert remove_hooks(merged) == {"hooks": {"Stop": [{"hooks": [OTHER]}]}}
    assert remove_hooks(merge_hooks({}, Path("/bin/agentbar-hook"))) == {}
