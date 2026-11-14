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

- a 4-character label;
- a row of 2×2 squares, one per running subagent, in that agent's state colour
  (up to 6);
- a 2px bar in the session's state colour underneath, touching the squares.

The label takes the most active state of the session and its subagents. A
session that is done while a background agent works shows a green label and
square over a still green bar. A subagent at a permission prompt turns its square
and the label amber and blinking, whatever the session itself is doing.

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

Labels use the bar's `condensed` font (7 px tall, most letters 4 px wide), which
fills the tile: `bab-` is exactly 18 px. Four full-width letters with no `-`, `i`,
`j`, `l` or `r` (such as `abcd`, or a duplicate like `bab1`) are 1 px wider, and
`m`, `v`, `w`, `x` add another pixel each; the bar clips the overflow at the tile
edge. Rows 0–1 stay blank above the label. Descenders (`g j p q y`) reach row 10,
leaving one blank row above the squares instead of three.

| State | Colour | Behaviour |
| --- | --- | --- |
| needs input | amber | blinks (bright/dim, 1 Hz) |
| working | green | a segment bounces between the bar's end caps (every 6 s); working agents' squares spin a bright pixel clockwise |
| done | green, still and solid | becomes idle after 1 hour |
| idle | steel-blue label, dim steel-blue bar | |

Working and done share green: working moves, done is a full, still bar. Red is
left out on purpose: the bar's own BUSY focus timer is red. See
`CLAUDE.md` for the reasons behind each colour.

A session gets a tile only once it does something: a prompt, a tool call or a
subagent. Claude Code also starts sessions nobody is using (spare background
processes, untouched background sessions), and those stay off the bar.
`agentbar status` lists them as hidden.

If there are more sessions than tiles, higher-priority states win a tile
(needs input > working > done > idle), counting each session's subagents.
Tiles stay in first-seen order. Squares follow the same rule within a tile.

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
font = "condensed"          # tiny, small, normal, condensed, bold, ...
text_y = 0
bar_height = 2
agent_size = 2              # subagent squares, on top of the bar
agent_gap = 1
show_idle = true
dim_factor = 0.2            # blink "off" brightness for needs input
shimmer = true              # animate working sessions and agents
shimmer_width = 5           # width of the bouncing segment
shimmer_factor = 0.6        # brightness of a working agent's square behind its pixel

[layout.colors]
working = "#00C850"
needs_input = "#FFC000"
done = "#00C850"
idle = "#385868"

[layout.text_colors]        # label colour, where it differs from the bar
idle = "#6090A8"

[timing]
done_decay_s = 3600
session_ttl_s = 7200        # only for sessions whose process couldn't be found
blink_period_s = 1.0
shimmer_step_s = 1.0        # seconds per animation frame (6 per bounce, 4 per spin)
busy_retry_s = 5.0
refresh_s = 60.0
```

## Claude Code state mapping

See `src/agentbar/adapters/claude_code.py`. In short:

- `UserPromptSubmit`, `PreToolUse`, `PostToolUse` → working
- `PermissionRequest`, `AskUserQuestion`, `Notification` (permission prompt) → needs input
- `Stop` → done
- `SessionEnd` → removed
- `SubagentStart` / `SubagentStop` → subagent square added / removed

Hooks fired inside a subagent carry `agent_id`. They change that subagent's
square, not the session, so a background agent doesn't flip a finished session
back to working. A `Stop` with no background tasks in flight clears any
leftover squares.

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
