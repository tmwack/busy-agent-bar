"""Today's Claude Code token usage, read from its session transcripts.

Claude Code writes one JSONL transcript per session under ~/.claude/projects, with
subagents' transcripts in nested subagents/ folders. Each assistant message records its
token usage. One API response is split over several entries that repeat the same usage,
and resumed or forked sessions copy earlier messages, so each message is counted once,
by its message id.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
# Everything a message used: fresh input, output, and prompt-cache writes and reads.
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class TokenCounter:
    """Tokens used today across every transcript. Each update reads only what's new."""

    def __init__(self, root: Path | None = None, today: Callable[[], date] = date.today) -> None:
        self.root = root or PROJECTS_DIR
        self._today = today
        self._day: date | None = None
        self._read_to: dict[Path, tuple[int, int]] = {}  # path -> (inode, bytes consumed)
        self._seen: set[str] = set()  # message ids already counted today
        self.total = 0

    def update(self) -> int:
        day = self._today()
        if day != self._day:  # a new day: start over from today's transcripts
            self._day, self._read_to, self._seen, self.total = day, {}, set(), 0
        midnight = datetime.combine(day, datetime.min.time()).timestamp()
        for path in self.root.rglob("*.jsonl"):
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime < midnight:
                continue  # untouched since before today, so nothing from today in it
            inode, offset = self._read_to.get(path, (st.st_ino, 0))
            if inode != st.st_ino or st.st_size < offset:
                offset = 0  # replaced or truncated: read it again (counted ids stay counted)
            if st.st_size > offset:
                self._read_to[path] = (st.st_ino, self._read(path, offset, day))
        return self.total

    def _read(self, path: Path, offset: int, day: date) -> int:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
        end = data.rfind(b"\n") + 1  # a partly written last line waits for the next update
        for line in data[:end].splitlines():
            self._count(line, day)
        return offset + end

    def _count(self, line: bytes, day: date) -> None:
        if b'"usage"' not in line:
            return  # most entries aren't messages; skip them before parsing
        try:
            entry = json.loads(line)
        except ValueError:
            return
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            return
        usage, message_id = message.get("usage"), message.get("id")
        if not isinstance(usage, dict) or not message_id or message_id in self._seen:
            return
        try:
            when = datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00")).astimezone()
        except (KeyError, ValueError):
            return
        if when.date() != day:
            return
        self._seen.add(message_id)
        self.total += sum(n for field in TOKEN_FIELDS if isinstance(n := usage.get(field), int))
