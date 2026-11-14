import io
import json
import socket
import threading

from agentbar import hook


def test_scalars_drops_bulk_and_truncates():
    out = hook.scalars({"a": "x" * 2000, "b": 1, "tool_input": {"big": 1}, "c": None})
    assert len(out["a"]) == hook.MAX_STR and out["b"] == 1 and out["c"] is None
    assert "tool_input" not in out


def test_no_daemon_is_silent_and_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENTBAR_SOCKET", str(tmp_path / "none.sock"))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b'{"session_id":"s"}')))
    assert hook.main(["claude-code"]) == 0
    assert capsys.readouterr() == ("", "")


def test_forwards_to_socket(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "harness_pid", lambda: 4242)
    path = tmp_path / "a.sock"
    monkeypatch.setenv("AGENTBAR_SOCKET", str(path))
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    got = {}

    def accept():
        conn, _ = server.accept()
        got["msg"] = json.loads(conn.makefile("rb").readline())
        conn.close()

    t = threading.Thread(target=accept)
    t.start()
    payload = {"session_id": "s", "hook_event_name": "Stop", "tool_input": {"x": 1}}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
    assert hook.main(["claude-code", "--resolve-pid"]) == 0
    t.join(2)
    server.close()
    msg = got["msg"]
    assert msg["source"] == "claude-code" and msg["payload"] == {"session_id": "s", "hook_event_name": "Stop"}
    assert msg["pid"] == 4242


def test_first_non_shell_skips_shells():
    ps = """    1     0 /sbin/launchd
  500     1 /Applications/Ghostty.app/Contents/MacOS/ghostty
  600   500 -zsh
  700   600 /Users/t/.local/share/claude/versions/2.1.141
  800   700 /bin/sh
  900   800 /Users/t/.local/share/uv/tools/agentbar/bin/python
"""
    table = hook.parse_ps(ps)
    assert hook.first_non_shell(table, 800) == 700
    assert hook.first_non_shell(table, 700) == 700
    assert hook.first_non_shell(table, 12345) is None


def test_scalars_forwards_list_lengths():
    out = hook.scalars({"background_tasks": [{"id": "t1"}, {"id": "t2"}], "session_crons": []})
    assert out == {"background_tasks_len": 2, "session_crons_len": 0}
