import json
import os
from datetime import date, datetime, timedelta

from agentbar.usage import TokenCounter

TODAY = date(2026, 11, 23)


def at(day, hour=12):
    """An ISO UTC timestamp, as Claude Code writes them, for a local time on `day`."""
    local = datetime(day.year, day.month, day.day, hour).astimezone()
    return local.astimezone().isoformat().replace("+00:00", "Z")


def assistant(message_id, day=TODAY, inp=10, out=5, cache_write=100, cache_read=1000):
    usage = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    }
    return json.dumps({"type": "assistant", "timestamp": at(day), "message": {"id": message_id, "usage": usage}})


def touch(path, day=TODAY):
    """Give a file a modification time on `day`, so the counter's midnight check sees it."""
    noon = datetime(day.year, day.month, day.day, 12).timestamp()
    os.utime(path, (noon, noon))


def write(path, *lines, partial="", day=TODAY):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write("".join(line + "\n" for line in lines) + partial)
    touch(path, day)


def counter(root, today=TODAY):
    return TokenCounter(root, today=lambda: today)


def test_counts_each_message_once_across_entries_and_forks(tmp_path):
    session = tmp_path / "-w-proj" / "a.jsonl"
    # One response split over three entries that repeat its usage, plus a user line.
    write(session, assistant("m1"), assistant("m1"), assistant("m1"), json.dumps({"type": "user"}))
    # A forked session copies m1 and adds m2.
    write(tmp_path / "-w-proj" / "b.jsonl", assistant("m1"), assistant("m2", inp=1, out=1, cache_write=0, cache_read=0))
    assert counter(tmp_path).update() == 1115 + 2


def test_only_today_and_subagents_included(tmp_path):
    write(tmp_path / "-w-a" / "s.jsonl", assistant("old", day=TODAY - timedelta(days=1)), assistant("new"))
    write(tmp_path / "-w-a" / "s" / "subagents" / "agent-1.jsonl", assistant("sub"))
    assert counter(tmp_path).update() == 2 * 1115


def test_reads_only_new_lines_and_waits_for_partial_ones(tmp_path):
    path = tmp_path / "-w" / "s.jsonl"
    write(path, assistant("m1"), partial=assistant("m2")[:20])
    c = counter(tmp_path)
    assert c.update() == 1115
    with path.open("a") as fh:
        fh.write(assistant("m2")[20:] + "\n")
    touch(path)
    assert c.update() == 2 * 1115


def test_skips_files_untouched_since_midnight(tmp_path):
    path = tmp_path / "-w" / "s.jsonl"
    write(path, assistant("m1"))
    yesterday = datetime(TODAY.year, TODAY.month, TODAY.day).timestamp() - 3600
    os.utime(path, (yesterday, yesterday))
    assert counter(tmp_path).update() == 0


def test_starts_over_each_day(tmp_path):
    days = [TODAY]
    path = tmp_path / "-w" / "s.jsonl"
    write(path, assistant("m1"))
    c = TokenCounter(tmp_path, today=lambda: days[0])
    assert c.update() == 1115
    days[0] = TODAY + timedelta(days=1)
    write(path, assistant("m2", day=days[0]), day=days[0])
    assert c.update() == 1115  # only the new day's message


def test_replaced_file_is_reread_without_double_counting(tmp_path):
    path = tmp_path / "-w" / "s.jsonl"
    write(path, assistant("m1"), assistant("m2"))
    c = counter(tmp_path)
    assert c.update() == 2 * 1115
    path.unlink()
    write(path, assistant("m1"))  # a new, shorter file
    write(path, assistant("m3"))
    assert c.update() == 3 * 1115
