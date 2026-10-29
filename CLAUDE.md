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
- **Sessions:** usually one at a time; tiles are small so a couple fit.
  Rotating through sessions is deferred until two tiles aren't enough.
- **Tile label:** project name (cwd basename), truncated to about 4 chars.
- **Needs input:** shown by colour plus blinking.
- **BUSY timer active:** yield, i.e. hide the tiles until it ends.
- **Platform:** macOS. The bar is connected over USB.

## Architecture

```
Claude Code hooks ─> agentbar-hook ─(unix socket)─> daemon: adapter → registry → layout → sink ─(HTTP)─> bar
```

| File | Role |
| --- | --- |
| `src/agentbar/hook.py` | Forwarder run by every hook. Stdlib only, prints nothing, always exits 0. Sends top-level scalar fields only. `--resolve-pid` finds the harness PID (nearest non-shell ancestor, one `ps` call). |
| `src/agentbar/adapters/` | Per-harness `normalize(payload, ts, pid) -> AgentEvent`. Register new ones in `__init__.py`. |
| `src/agentbar/model.py` | `AgentState` (its int value is tile priority), `AgentEvent`, `Session`. |
| `src/agentbar/registry.py` | Applies events; ignores out-of-order state events; decays DONE→IDLE; drops sessions whose PID died (TTL if no PID is known). |
| `src/agentbar/layout.py` | Pure function: sessions → draw-element dicts. Element ids are `10*(slot+1)` (bar) and `+1` (text). |
| `src/agentbar/sink.py` | `BusyBarSink`: sends only changed elements; on 409 clears its tiles and retries every `busy_retry_s`. `LogSink` is used for `--dry-run`. |
| `src/agentbar/daemon.py` | asyncio Unix-socket server and render loop (1 Hz; 2 Hz while blinking). Full redraw every `refresh_s`. |
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
| `Stop` | DONE |
| `SessionEnd` | session removed |

PIDs are only resolved on `SessionStart` and `UserPromptSubmit`, so the `ps`
cost isn't paid on every tool call.

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
- Element ids double as z-order (higher sits on top).

**Priority and BUSY timer**
- A lower-priority draw is refused with `409 Not drawn due to low priority`.
- A running BUSY session outranks priority 50; `busylib` uses 91 to draw
  above it.
- Timer state: `GET /api/busy/snapshot` returns the last applied snapshot,
  not live state. `busylib.features.timer_state()` advances it to now.

**Library quirks**
- `busylib` logs every request at INFO. The CLI turns that down unless `-v`
  is passed.

## Status

- Never run on macOS or against a real bar.
- Verified in a Linux container: 22 unit tests, and an end-to-end dry-run
  (real hook payloads → daemon → `agentbar status`).
- Rendered elements validate against `busylib.types.DisplayElements`.
- Hook forwarder cost: about 31 ms per call in the container. Each tool call
  fires two hooks.

## Verify on device first

1. Re-posting an element with an existing `id` replaces it. Look for
   ghosting or duplicates when a tile changes state.
2. The `small` font fits 4 chars in 18 px; otherwise tune `font`,
   `tile_width` or `name_chars`.
3. Other apps' drawings stay visible next to the tiles.
4. Tiles hide during a BUSY session (409 path) and come back afterwards.
5. Whether `Stop` fires on an Esc interrupt. If not, the tile stays WORKING
   until the next prompt.
6. On macOS, `--resolve-pid` lands on the Claude Code process. Check the
   `pid` column in `agentbar status`.

## Known gaps / next ideas

- **Parallel-tool race:** a parallel tool's `PostToolUse` can flip
  NEEDS_INPUT back to WORKING while a permission dialog is still open. Only
  partly mitigated by the out-of-order guard.
- **Hook latency:** if it's noticeable, replace the Python forwarder with a
  shell `nc -U` one-liner. The daemon would then need to accept the raw
  payload plus a source line.
- **Session rotation** when sessions outnumber tiles (currently the
  highest-priority states win).
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
uv run --extra dev pytest
uv run --extra dev ruff format     # format
uv run --extra dev ruff check      # lint (--fix to autofix)
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
