---
description: Cross-cutting tool-usage etiquette for the ableton MCP — restart protocol, write-lag, hot-swap, undo, MIDI extended API, connection triage.
allowed-tools: ["Bash"]
---

# /ableton:best-practices

The hard-won rules for driving Ableton Live through this MCP reliably. Load this into context before a multi-step Live session, or whenever a Live call behaves unexpectedly.

## Return envelope: every tool returns `{ok, data|error}`

Every tool returns a JSON string in one uniform shape:

- Success → `{"ok": true, "data": <result>}`
- Failure → `{"ok": false, "error": "<message>"}`

Check `ok` first; never string-sniff for "Error". A tool's docstring `Returns JSON {…}` describes the **`data`** payload (what's nested under `data` on success). Reads put their object under `data`; write tools put a short confirmation message or the affected fields under `data`. Errors are surfaced as `{"ok": false, "error": …}` rather than raised, so a failed call still returns a parseable string.

Large readers (`get_browser_tree`, `get_browser_items_at_path`, `get_arrangement_clips`, `list_device_presets`) cap their lists with a `limit` (default 200) and report `count` / `returned` / `truncated` inside `data` — raise `limit` or narrow the path/category for more.

## Verify, don't trust the return value (write-lag)

Song-level property writes apply **asynchronously inside Live**, even within one Remote-Script task. A handler that sets a property and returns it in the same call frequently returns the **pre-write** value. The mutation is reliable; the confirmation dict is not.

- After any transport/record/loop/tempo/punch/metronome write → confirm with a separate `get_transport`.
- After structural changes (tracks/scenes) → confirm with a separate `get_session_info`.
- After `undo`/`redo` → structural reads can be stale for ONE call; read **twice**.

## MIDI notes: extended API only

Use `add_notes_to_clip`, `replace_clip_notes`, `modify_clip_notes`, `remove_clip_notes`. **Never** legacy set_notes/remove_notes — they trigger a blocking modal in Live that stalls the Remote Script main thread and times out the socket ("No data received"), even though the edit may have applied. Edit notes in place by `note_id` (`modify_clip_notes`) rather than remove + re-add. `quantize_clip` is safe (no modal).

## Groove & swing: two distinct paths

Three different things, do not confuse them:

- `set_swing_amount` / `set_groove_amount` are GLOBAL settings. `set_swing_amount` only affects FUTURE quantize/add operations - it does not retroactively swing notes already in a clip. `set_groove_amount` scales how strongly an ASSIGNED clip groove is applied.
- `swing_clip` BAKES swing into the notes of an existing clip (shifts off-beat note start-times). Destructive but reversible with `undo`; works best on grid-quantized parts. Accepts a 0-1 fraction or an MPC-style percent ("66%").
- `assign_groove_to_clip` binds a Groove-Pool groove to a clip so its feel is applied non-destructively at playback (then `set_groove_amount` scales it). Pick the groove by pool index or exact name; list the pool with `get_groove_pool`. The groove must ALREADY be in the Groove Pool - there is no MCP path to load a factory `.agr` into the pool, so drag one in first if `get_groove_pool` returns empty. Clearing a clip's groove via MCP is not supported (Live's API rejects a null groove).

## Loading devices HOT-SWAPS

`load_instrument_or_effect` / `load_preset` / `load_drum_kit` REPLACE the existing instrument on a track — they don't append. For experiments, load onto an EMPTY regular track and `delete_device`/`delete_track` after; never onto a patch you care about.

## Device-tool asymmetry

`get_device_parameters` / `set_device_parameter` accept a `track_type` and reach return/master-track devices too (since PR #24), as do `get_device_info`/`get_rack_macros`/`set_rack_macro`/`set_chain_property`/`set_device_on`/`delete_device`. The pair that stays regular-track-only is `get_automation` / `set_automation`.

## Track-type differences

Return / master / group tracks have **no `.arm`**; group tracks have no monitoring; only regular tracks expose input monitoring. Probe optional endpoints defensively — don't assume a field exists on every track type. No LOM call creates a group track (grouping is UI-only, ⌘G).

## Automation envelopes

Reads are **sampled only** (`value_at_time`) — there's no breakpoint enumeration, and sampling a step's exact left edge returns the pre-step value (sample slightly inside). Writes: `insert_step` makes FLAT segments, `duration=0` is a no-op; the server auto-tiles value-only points into a staircase. No linear ramps exist in the LOM.

## Re-read state every session

The open Live set changes between sessions. Always `get_session_info` + `get_track_info` at the start of a task; never carry a track index forward from a previous conversation.

## Connection triage

"Could not connect to Ableton" on the first call after a restart is usually just the reconnect race — retry once. If it persists:

```bash
pgrep -fl "Ableton Live" || echo "Live not running"
lsof -nP -iTCP:9877 -sTCP:LISTEN || echo "Nothing listening on 9877 — Control Surface not selected, or Live needs a restart"
```

Remote Script load errors / command logs live in `~/Library/Preferences/Ableton/Live 1[12]*/Log.txt` (grep `AbletonMCP` / `Traceback`). Re-run `/ableton:setup` if the Remote Script half isn't loaded.

## (Maintainers only) restart protocol

If you EDIT the plugin's code, changes don't hot-reload:
- Edited the Remote Script (`remote_script/...`)? Reinstall (`scripts/install_remote_script.sh`) then quit + reopen Live so it re-scans Control Surfaces.
- Edited `server.py` or any `*_utils.py` it imports? Restart Claude Code (the MCP server loads at session start).
- Batch both, then do ONE reinstall + ONE dual-restart.
