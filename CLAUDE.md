# agentbar

Shows coding-agent session state on a BUSY Bar. The core is harness-agnostic;
v1 ships only a Claude Code adapter.

## Decisions (settled with Tyler)

- **What it shows:** agent state only (working / needs input / done, plus
  idle). Not usage quota, context %, or Anthropic service status.
- **Where it runs:** a Python daemon on the same Mac as Claude Code, drawing
  through the bar's local HTTP API. Not an on-device JS app (that runtime is
  still WIP). Not a bsbctl plugin (bsbctl is Go-only).
- **Layout:** a region of side-by-side session tiles on the front display.
  The rest of the display stays free for other apps.
- **Subagents:** each running subagent gets a 2×2 square sitting on top of
  its session's bar (up to 6 per tile), coloured by that agent's state. The
  bar keeps the main session's state. The label takes the most active state
  of the session and its agents, so a done session with a working background
  agent has a green label over a still green bar with a spinning square. A square disappears on
  `SubagentStop`.
- **Sessions:** at most 3 at once. Three 18 px tiles take 56 px and leave
  16 px for other apps. Rotating through sessions is deferred.
- **Only sessions with activity get a tile:** a session is hidden until its
  first prompt, tool call or subagent. Claude Code fires `SessionStart` for
  processes nobody is using: the pre-started `bg-spare` process its
  background daemon keeps ready, the session of a `claude` used only to get
  back to a background session, and background sessions that never got a
  prompt. Running `claude` in a Macuake tab parked in `~/src/twack/charlie`
  put three such tiles on the bar (2026-11-14). Hiding "background" processes
  instead isn't an option: a session you're using can also run under the
  daemon's `--bg-pty-host`. `agentbar status` still lists hidden sessions.
- **Tile label:** 4 characters: initials of the session title (set with
  `--name` or `/rename`), else of the cwd basename. Words split on `-`, `_`,
  spaces and case changes; missing characters are `-`. `busy-agent-bar` →
  `bab-`, `istari-rfc-equivalency` → `ire-`, `mcpTenancy` → `mt--`,
  `agentbar` → `a---`. Drawn in the `condensed` font at `y = 0`, so letters
  use rows 2–8 and rows 0–1 and 9–11 stay blank. Descenders (`g j p q y`)
  reach row 10, leaving one blank row above the squares, which is accepted.
  `bab-` fills the 18 px exactly. Four full-width letters (no `- i j l r`),
  or a duplicate digit (`bab1`), are clipped by 1 px, and each `m v w x` adds
  a pixel; also accepted.
- **Palette** (sent value → how it shows on the LEDs after gamma 2.8 →
  luminance):

  | State | Sent | Shows as | Luminance |
  | --- | --- | --- | --- |
  | needs input | amber `#FFC000` | `#FFB300` | 0.536 |
  | working | green `#00C850` | `#00BD38` | 0.365 |
  | done | green `#00C850` (solid, still) | `#00BD38` | 0.365 |
  | idle label | steel blue `#6090A8` | `#487C97` | 0.181 |
  | idle bar | dim steel blue `#385868` | `#204050` | 0.045 |

  Reasons, chosen with Tyler (sources read 2026-11-13):
  - **Done is a full, still green bar** (Tyler, 2026-11-14). It shares
    working's green; working moves (dark bar, bouncing segment) and done
    doesn't. A brief cyan done (warm-to-cool order) was tried the same day
    and dropped.
  - **No red.** The firmware already uses red for its own BUSY focus timer
    and status lights
    ([`busy_presets.c`](https://raw.githubusercontent.com/busy-app/busybar-firmware/HEAD/applications/main/busy/busy_presets.c),
    [`busy_timer_status_lights.c`](https://raw.githubusercontent.com/busy-app/busybar-firmware/HEAD/applications/services/busy_timer/busy_timer_status_lights.c)),
    and presence lights use red for "do not disturb"
    ([Teams](https://learn.microsoft.com/en-us/microsoftteams/presence-admins),
    page dated 2026-07-16).
  - **Prior art.** Amber for waiting follows other agent-status tools, e.g.
    [bsbctl](https://github.com/lxdb/bsbctl) and
    [busybar-ai-progress](https://github.com/alexsuslin/busybar-ai-progress).
    Green for done matches them too; they mostly use cyan or blue for
    working, which here is green told apart by motion.
  - **Brightness order.** Needs input is the brightest state; the old red
    was the dimmest.
  - **Idle is dim steel blue,** about half as bright as done, so a parked
    tile never outshines a finished one.
  - **Colour blindness.** The old red/orange/green set is the hardest one
    for red-green colour blindness
    ([Okabe & Ito](https://jfly.uni-koeln.de/color/), 2002, revised 2008).
    Each state now also has a non-colour cue:
- **Needs input:** amber plus blinking.
- **Working:** green, with motion. The session's bar goes dark except for
  its two outer columns (end caps) and a 5 px segment that bounces between
  them over four stops in six frames (1-2-3-4-3-2, touching a cap at either
  end; steps of 4, 3 and 4 px, so the two middle stops overlap on the bar's
  centre columns 8–9), one frame every `shimmer_step_s` (1 s), so a full bounce takes 6 s. A working agent's 2×2
  square is dim with one bright pixel stepping clockwise on the same frame
  clock (four frames per turn).
  That's about one draw a second. An earlier two-colour gradient shimmer
  (2026-11-14) didn't read as motion on the 2 px bar, so it was replaced.
  Labels stay still.
- **Done:** a full, still green bar.
- **Idle:** steel-blue label over a dim steel-blue bar, so idle tiles read
  as parked but the label stays legible.
- **BUSY timer active:** yield, i.e. hide the tiles until it ends.
- **Platform:** macOS. The bar is connected over USB.

## Architecture

```
Claude Code hooks ─> agentbar-hook ─(unix socket)─> daemon: adapter → registry → layout → sink ─(HTTP)─> bar
```

| File | Role |
| --- | --- |
| `src/agentbar/hook.py` | Forwarder run by every hook. Stdlib only, prints nothing, always exits 0. Sends top-level scalar fields, plus each top-level list's length as `<key>_len`. `--resolve-pid` finds the harness PID (nearest non-shell ancestor, one `ps` call). |
| `src/agentbar/adapters/` | Per-harness `normalize(payload, ts, pid) -> AgentEvent`. Register new ones in `__init__.py`. |
| `src/agentbar/model.py` | `AgentState` (its int value is tile priority), `AgentEvent`, `Session`, `Agent` (a subagent inside a session). `Session.top_state` is the most active state of the session and its agents. |
| `src/agentbar/registry.py` | Applies events; ignores out-of-order state events; decays DONE→IDLE; drops sessions whose PID died (TTL if no PID is known). Events with an `agent_id` change that agent only, never the session's state. |
| `src/agentbar/layout.py` | Pure function: sessions → draw-element dicts. `initials()` builds labels. Each element's `z_index` is its id. Element ids are `100*(slot+1)` plus an offset: `+0` bar, `+1` label, `+2`/`+3` end caps and `+4` bouncing segment while working, `+10`… agent squares, `+20`… each working agent's bright pixel. |
| `src/agentbar/sink.py` | `BusyBarSink`: sends only changed elements; on 409 clears its tiles and retries every `busy_retry_s`. `LogSink` is used for `--dry-run`. |
| `src/agentbar/daemon.py` | asyncio Unix-socket server and render loop (1 Hz; 2 Hz while blinking; also wakes on each shimmer frame). Full redraw every `refresh_s`. |
| `src/agentbar/install.py` | Idempotently merges hooks into `~/.claude/settings.json` (backs it up first; leaves non-agentbar hooks alone). Installs the launchd agent `com.agentbar.daemon`. |
| `src/agentbar/config.py` | Loads `~/.config/agentbar/config.toml` (all keys optional). Env overrides: `AGENTBAR_CONFIG`, `AGENTBAR_SOCKET`. |

## Claude Code state mapping

| Hook event | State |
| --- | --- |
| `SessionStart` (startup/resume/clear) | IDLE |
| `SessionStart` (compact) | no change |
| `UserPromptSubmit` | WORKING |
| `PreToolUse` | WORKING |
| `PreToolUse` with `AskUserQuestion` | NEEDS_INPUT |
| `PostToolUse`, `PostToolUseFailure` | WORKING |
| `PermissionRequest` | NEEDS_INPUT |
| `Notification` (`permission_prompt`, `elicitation_dialog`) | NEEDS_INPUT |
| `Notification` (`idle_prompt` and other types) | ignored on purpose |
| `Stop` | DONE; also clears agents when `background_tasks` is empty |
| `SessionEnd` | session removed |
| `SubagentStart` | agent added, WORKING |
| `SubagentStop` | agent removed |

Hooks fired inside a subagent carry `agent_id` and keep the mapping above,
but change that agent's square instead of the session's state. Without this, a
background agent's tool calls flipped a finished session back to WORKING.
`SubagentStop` also fires for Claude Code's internal agents (prompt
suggestions, `/btw`) with an empty `agent_id`; those are ignored.

PIDs are only resolved on `SessionStart` and `UserPromptSubmit`, so the `ps`
cost isn't paid on every tool call.

`session_title` also arrives only on `SessionStart` and `UserPromptSubmit`,
and only for sessions with a custom name. The registry keeps the last title it
saw, so a `/rename` shows on the tile after the next prompt.

## Device facts (from the official `busylib` ≥2.6)

**Displays**
- Front: 72×16 RGB LED.
- Back: 160×80 OLED, 16 grey levels. Not used yet.

**Connection**
- USB: `10.0.4.20`, no auth on current firmware.
- Wi-Fi: the bar's LAN IP plus an access-key PIN (`token`).
- The bar serves its raw API docs at `http://10.0.4.20/docs`.

**Drawing**
- Draw: `POST /api/display/draw` with `application_name`, `priority` (1–100,
  default 50), optional `led_notification_color`, and `elements`.
- Element types: text, image, animation, countdown, rectangle.
- Text fonts: tiny, small, normal, condensed, bold, large, extra_large, global.
- Clear: `DELETE /api/display/draw`, optionally with `element_ids`. It is
  scoped to `application_name` and leaves other apps' drawings alone.
- Draw calls add to what's on screen.
- Stacking order is each element's `z_index` (higher on top), not its id.
  Without one, the firmware assigns 0, 10, 20… by the element's position
  within that one draw request (`api_display.c`, `default_z_index`). An
  element re-sent alone later can then tie with, and sink under, one drawn
  earlier. agentbar sends `z_index` = id on every element. This was seen on
  the bar, 2026-11-14: the bounce segment vanished under the dark bar, and
  the agent pixel under its square.
- Re-posting an element id updates the existing widget in place (seen on the
  bar, 2026-11-14). A rectangle's `solid` fill sets only the main colour and
  never resets an earlier gradient's direction or end colour
  (`rectangle_widget_set_background` in
  `applications/services/canvas/widgets/rectangle.c`). So a bar that was a
  `gradient_h` keeps fading to the old colour after a `solid` update. Bars
  are therefore always sent as `gradient_h`, `[c, c]` when not shimmering.

**Priority and BUSY timer**
- A lower-priority draw is refused with `409 Not drawn due to low priority`.
- A running BUSY session outranks priority 50; `busylib` uses 91 to draw
  above it.
- Timer state: `GET /api/busy/snapshot` returns the last applied snapshot,
  not live state. `busylib.features.timer_state()` advances it to now.

**Fonts** (from the firmware source, `busy-app/busybar-firmware`)
- `small` is `busy_regular_5`, compiled into the firmware
  (`lib/lvgl_addons/fonts/lv_font_busy_regular_5.c`). Line height 9, baseline
  2: capitals sit on rows 2–6 below the text element's `y`, descenders on
  row 7.
- Advance widths: most lowercase letters and digits 4 px (3 px glyph + 1 px
  gap); `f j r t 1 -` 3 px; `i l` 2 px; `m w` 6 px.
- API font names map to firmware fonts in
  `applications/services/web_server/http_api/api_display.c`: `tiny` →
  `busy_tiny`, `small` → `busy_regular_5`, `normal` → `busy_regular_7`,
  `condensed` → `busy_condensed_7`, `bold` → `busy_bold_7`, `large` →
  `busy_regular_9`, `extra_large` → `busy_bold_10`, `global` →
  `lana_pixel_regular_11`, `superscript` → `busy_superscript_7`.
- `condensed` (the label font, measured from
  `assets/shared/fonts/ttf/busy_condensed_7px.ttf`, which the firmware converts
  at size 16): line height 11, baseline 2. Ascenders and capitals on rows 2–8
  below `y`, x-height rows 4–8, descenders rows 9–10. Lowercase advance 5 px
  (4 px glyph + 1 px gap), digits 5 px, `i j l r -` 4 px, `m v w x` 6 px.
  Capitals are 6 px, too wide for four in a tile. `normal` has the same
  lowercase but 6 px digits.
- A text element with a `width` and no `scroll_rate` is clipped at that width
  (`applications/services/canvas/canvas_widgets.c`); with `scroll_rate` it
  scrolls.

**LED output** (from the firmware source)
- The front display raises each colour channel to the power 2.8 at full
  brightness (2.5 at the lowest) before driving the LEDs
  (`applications/services/front_display/front_display_driver.c`). Dark values
  almost vanish: `#303030` drives about 1% of full output, `#808080` about
  14%, the idle label `#6090A8` about 18% luminance.

**Library quirks**
- `busylib`, and its HTTP client's `httpx2` logger, each log every request
  at INFO. The CLI turns both (and `httpx`) down unless `-v` is passed.

## Status

- Never run on macOS or against a real bar.
- Verified in a Linux container: 38 unit tests, and an end-to-end dry-run
  (real hook payloads → daemon → `agentbar status`).
- Rendered elements validate against `busylib.types.DisplayElements`.
- Hook forwarder cost: about 31 ms per call in the container. Each tool call
  fires two hooks.

## Verify on device first

1. Re-posting an element with an existing `id` updates it in place
   (confirmed 2026-11-14, see Drawing). Still look for ghosting or
   duplicates when a tile changes state.
2. Other apps' drawings stay visible next to the tiles.
3. Tiles hide during a BUSY session (409 path) and come back afterwards.
4. Whether `Stop` fires on an Esc interrupt. If not, the tile stays WORKING
   until the next prompt.
5. Subagent `PermissionRequest` and `Notification` hooks carry `agent_id`,
   and internal agents don't fire `SubagentStart` (no stray squares).
6. On macOS, `--resolve-pid` lands on the Claude Code process. Check the
   `pid` column in `agentbar status`.
7. Whether the bouncing segment reads as motion at 1 s per frame, and the
   bars stay one even colour after it stops (the `gradient_h` workaround).
8. Whether a green 2×2 agent square is visible, and whether the bounce or the spinning pixel
   ghosts or flickers.
9. Whether an idle steel-blue tile is clearly distinct from a done tile next to
   it.

## Known gaps / next ideas

- **Parallel-tool race:** a parallel tool's `PostToolUse` can flip
  NEEDS_INPUT back to WORKING while a permission dialog is still open. Only
  partly mitigated by the out-of-order guard.
- **Hook latency:** if it's noticeable, replace the Python forwarder with a
  shell `nc -U` one-liner. The daemon would then need to accept the raw
  payload plus a source line.
- **Session rotation** when sessions outnumber tiles (currently the
  highest-priority states win).
- **Tile placement:** tiles fill the region from the left, so a single
  session sits at x=16–33 with two empty slots to its right.
- **Label collisions:** different names with the same initials are told apart
  only by the duplicate digit (`bab1`, `bab2`).
- **Back OLED** for detail: full project name, current tool.
- **`led_notification_color`** for NEEDS_INPUT.
- **More adapters:** Codex, others.
- **Prior art:** bsbctl (Go, macOS) has a Codex app with
  activity/approval/question states; BarPilot does Claude plan-usage
  monitoring.

## Commands

```sh
uv tool install --editable .     # install
agentbar install                 # hooks + launchd agent; --no-agent = hooks only
agentbar status                  # tracked sessions, bar reachability
agentbar run --dry-run -v        # foreground, no bar (stop the agent or set AGENTBAR_SOCKET)
agentbar uninstall
uv run pytest
uv run ruff format               # format
uv run ruff check                # lint (--fix to autofix)
```

Logs: `~/Library/Logs/agentbar.log`.

## Working conventions

- When interpretations are ambiguous, confirm before acting rather than
  picking one and running with it.
- Keep `hook.py` stdlib-only and fail-silent. It runs on every tool call and
  must never block or break the harness.
- Keep `layout.py` pure; put device I/O in `sink.py`.
- Code is formatted with `ruff format` and must pass `ruff check` (rules in
  `pyproject.toml`).
- No merge commits: merge PRs with squash or rebase, and update branches by
  rebasing onto `main`, never by merging `main` in.
- Tyler authenticates git with SSH. Use `git@github.com:owner/repo.git` URLs
  in instructions and docs, not HTTPS.
