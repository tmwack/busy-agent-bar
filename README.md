# agentbar

Shows coding-agent session state on a BUSY Bar. v1 ships a Claude Code adapter;
the core is harness-agnostic.

```
Claude Code hooks ──> agentbar-hook ──(unix socket)──> agentbar daemon ──(HTTP)──> BUSY Bar
                      stdlib-only,                     adapter → registry
                      always exit 0                    → layout → sink
```

## Install (macOS)

```sh
uv tool install /path/to/agentbar     # or: uv tool install --editable .
agentbar install                      # hooks in ~/.claude/settings.json + launchd agent
agentbar status                       # sessions the daemon is tracking
```

`install` backs up `~/.claude/settings.json` before editing it, and leaves hooks
that aren't agentbar's untouched. Re-running it is safe. Hooks take effect in new
Claude Code sessions.

Logs: `~/Library/Logs/agentbar.log`.

Remove everything: `agentbar uninstall`.

Run without a bar (stop the agent first, or set `AGENTBAR_SOCKET` to another path):

```sh
agentbar run --dry-run -v
```

## Display

The front display gets a fixed region of `max_tiles` tiles, right-aligned by
default. The rest of the display is left to other applications. Each tile shows:

- a 4-character label in the state colour;
- a 2px bar in the state colour underneath.

The label is the initials of the session's name, set with `claude --name` or
`/rename`. Unnamed sessions use the project folder (cwd basename) instead.
Words are split on `-`, `_`, spaces and case changes, and missing characters
are filled with `-`:

| Name | Label |
| --- | --- |
| `busy-agent-bar` | `bab-` |
| `istari-rfc-equivalency` | `ire-` |
| `mcpTenancy` | `mt--` |
| `agentbar` | `a---` |
| `one-two-three-four-five` | `ottf` |

Sessions with the same label get a digit in place of the last character:
`bab1`, `bab2`.

Four characters fit an 18 px tile in the bar's `small` font. A label with two
or more `m` or `w` is a pixel or two wider, and the bar clips it at the tile edge.

| State | Colour | Behaviour |
| --- | --- | --- |
| working | amber | |
| needs input | red | blinks (bright/dim, 1 Hz) |
| done | green | becomes idle after 1 hour |
| idle | grey label, dark grey bar | |

If there are more sessions than tiles, higher-priority states win a tile
(needs input > working > done > idle). Tiles stay in first-seen order.

While a native BUSY timer session is running, the bar refuses lower-priority
drawings with `409`. The daemon then clears its tiles and retries every 5 s,
redrawing once the session ends.

## Config

`~/.config/agentbar/config.toml`. Every key is optional; defaults shown.

```toml
[busybar]
host = "10.0.4.20"          # USB. For Wi-Fi: the bar's LAN IP plus `token`
# token = "1234"
application_name = "agentbar"
priority = 50

[layout]
# x = 0                     # left edge of the region; omit to right-align
tile_width = 18
gap = 1
max_tiles = 3
name_chars = 4              # label length
font = "small"              # tiny, small, normal, condensed, bold, ...
text_y = 1
bar_height = 2
show_idle = true
dim_factor = 0.2

[layout.colors]
working = "#FFA000"
needs_input = "#FF1E1E"
done = "#00C850"
idle = "#303030"

[layout.text_colors]        # label colour, where it differs from the bar
idle = "#808080"

[timing]
done_decay_s = 3600
session_ttl_s = 7200        # only for sessions whose process couldn't be found
blink_period_s = 1.0
busy_retry_s = 5.0
refresh_s = 60.0
```

## Claude Code state mapping

See `src/agentbar/adapters/claude_code.py`. In short:

- `UserPromptSubmit`, `PreToolUse`, `PostToolUse` → working
- `PermissionRequest`, `AskUserQuestion`, `Notification` (permission prompt) → needs input
- `Stop` → done
- `SessionEnd` → removed

`idle_prompt` notifications are ignored, so a finished session stays "done"
instead of switching to "needs input".

Session names: `SessionStart` and `UserPromptSubmit` carry `session_title` when
the session has a custom name. A `/rename` shows on the tile after the next
prompt.

Liveness: on `SessionStart` and `UserPromptSubmit`, the forwarder records the
Claude Code PID (nearest non-shell ancestor, found with one `ps` call). The
daemon drops the session when that process exits. Long-running tools therefore
don't expire.

## Verify on the device

These are assumptions the code makes that couldn't be checked without a bar:

1. Re-posting an element with an existing `id` replaces it rather than adding
   a duplicate. Watch for flicker or ghosting when a tile changes state.
2. Elements from other applications stay visible next to the tiles.
3. During a BUSY session, draws fail with 409 and the tiles reappear afterwards.
4. If `Stop` doesn't fire when you interrupt Claude with Esc, the tile stays
   "working" until the next prompt.

## Adding a harness

1. Add `adapters/<name>.py` with `SOURCE` and
   `normalize(payload, ts, pid) -> AgentEvent | None`.
2. Register it in `adapters/__init__.py`.
3. Point the harness's hooks at `agentbar-hook <SOURCE>`. Pass
   `--resolve-pid` on infrequent events.

The forwarder sends only top-level scalar fields of the hook payload.

## Development

```sh
uv run pytest
uv run ruff format     # format
uv run ruff check      # lint
```
