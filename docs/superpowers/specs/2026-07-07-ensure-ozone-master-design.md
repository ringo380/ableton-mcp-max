# ensure_ozone_master - Design

**Date:** 2026-07-07
**Status:** Approved (design), pending implementation plan
**Author:** ableton-mcp-max

## Goal

One deterministic MCP tool, `ensure_ozone_master`, that prepares the master track
for mastering so the flow is hands-off: guarantee exactly one enabled Ozone 12 on
the master, older Ozone versions disabled (not deleted), and the instance's state
blob immediately authorable by the downstream blob tools. It is called before
`recommend_master` / `apply_master`; `apply_master` keeps its own detect-and-error
as a safety net.

## Motivation

`apply_master` and the `get_ozone_state` / `set_ozone_state` blob tools require an
Ozone 12 instance already on the master - they detect-and-error if it is absent and
do not load it. Today the user must load and position Ozone 12 by hand, and if an
older Ozone (9/10/11) is present the mastering tools can target the wrong device.
This tool closes that orchestration gap.

## Live-verified findings (de-risk spike, 2026-07-07)

Run against a real set (`ozone_idbase_probe.als`, master already had `Ozone 12` @0 +
`MCP Tap` @1):

1. `load_instrument_or_effect` with `track_type="master"` **appends** Ozone 12 (a
   fresh instance went to index 2; existing devices untouched). Non-destructive.
2. `set_device_on(false)` disables a master device cleanly; `delete_device`
   re-indexes correctly. Both work regardless of window state.
3. An **already-saved** Ozone 12 reads its full blob via `get_ozone_state` (path
   resolves, ~40 modules).
4. A **freshly loaded** Ozone 12 does NOT immediately yield a readable blob. Every
   structural change (load AND delete) dirties the set and leaves a racy window
   state: loading a VST3 auto-opens a transient nameless `AXFloatingWindow` (the
   Ozone editor) that briefly becomes Live's key window, and even after it settles
   the front-window title can momentarily read empty.
5. Root cause (mechanistic): `_save_set_impl` saves via the File menu
   (focus-independent) but classifies untitled from `_live_window_title()`; when the
   title transiently reads `""`, `is_untitled_title("")` returns True and the save is
   reported as untitled/failed. `get_ozone_state` / `set_ozone_state` resolve the
   `.als` path from Live's log, which also lags right after a structural change,
   surfacing as `"Could not resolve the current set's .als path"`. While in this
   state, reads fail for **every** device on the master, not just the fresh one.
6. Mitigation (proven live): a **save-with-retry** fixes it. The first `save_set`
   after a structural change often caught the transient empty-title state
   (`saved:false`, `title:""`); an immediate retry returned `saved:true` with the
   correct title, after which both the fresh and existing instances read their full
   blobs and the path resolved.

## Architecture

Follows the repo's pure-resolver + thin-executor pattern (as in `master_select.py`
+ the `recommend_master` / `apply_master` executors).

### `ableton_mcp_max/master_ozone_utils.py` (new, pure, unit-tested)

No I/O. Given a normalized list of the master's devices, decide the action plan.

- Input: `devices` = ordered list of `{index, name, is_on}` (as read from
  `get_device_info` per device).
- Exact-match detection: an entry is a full Ozone suite only when its `name` is
  exactly one of `Ozone 9`, `Ozone 10`, `Ozone 11`, `Ozone 12`. Never a substring -
  so the component plugins (`Ozone 12 Maximizer`, `Ozone 12 Equalizer`, `Ozone 12
  Dynamics`, ...) are ignored.
- Output plan: `{target_index, action, disable_indices, load_required}` where
  `action` is one of `"reused"`, `"reused_reenabled"`, `"loaded"`.

Decision logic:
- `disable_indices` = every index whose name is exactly `Ozone 9/10/11`.
- If one or more `Ozone 12` exist: pick the lowest index as `target_index`.
  `action = "reused"` if it is already on, else `"reused_reenabled"` (executor will
  `set_device_on(true)` it). `load_required = False`.
- Else: `target_index = None`, `load_required = True`, `action = "loaded"` (the
  executor loads, then the new instance's index becomes the appended tail).

### `ensure_ozone_master` executor in `server.py` (new `@mcp.tool()`)

Signature: `ensure_ozone_master(ctx, track_index: int = 0, track_type: str = "master")`.

Steps:
1. `get_ableton_connection()` - fail fast if Live is unreachable.
2. **Enumerate** master devices: walk `device_index` from 0 upward via
   `get_device_info`, collecting `{index, name, is_on}`, until an index errors /
   returns no device (bounded scan).
3. Call `master_ozone_utils` on the enumerated list to get the plan.
4. **Disable** each `disable_index` via `set_device_on(false)` (never delete).
5. **Reuse / load:**
   - `reused_reenabled`: `set_device_on(true)` on `target_index`.
   - `reused`: no-op.
   - `loaded`: `load_instrument_or_effect(track_index, "query:Plugins#VST3:iZotope:Ozone%2012", track_type="master")`;
     then re-enumerate to find the appended Ozone 12's index (lowest new
     `Ozone 12` not present before) and set it as `target_index`.
6. **Save-with-retry guarantee** (`_master_blob_ready` helper): after the structural
   changes, loop up to N times (bounded, with a short settle sleep between tries):
   - call `save_set` (empty name, in-place save of the titled set),
   - accept only when it returns `saved:true` with a non-empty title that is not
     the untitled sentinel,
   - then probe `get_ozone_state(track_index, target_index, track_type)` and accept
     only when `ok:true`. Retry on the transient `"Set is untitled"` /
     `"Could not resolve the current set's .als path"` errors.
   Return `blob_ready` reflecting whether the probe finally succeeded.
7. Return.

## Return shape

```
{ok: true, data: {
  device_index: <int>,          # the Ozone 12 to hand to apply_master
  action: "reused" | "reused_reenabled" | "loaded",
  disabled_indices: [<int>, ...],
  blob_ready: <bool>            # true once the get_ozone_state probe succeeded
}}
```

The `/ableton:produce` skill (and a human caller) passes `data.device_index` straight
into `apply_master(device_index=...)`.

## Precondition & error handling

- **Set must already be saved to a file.** `save_set()` with no name cannot save an
  untitled set. If enumeration/save finds the set untitled, return
  `{ok:false, error: "Save the set to a file first (it is untitled), then retry."}` -
  the same precondition `apply_master` / `set_ozone_state` already carry.
- If `load_instrument_or_effect` fails, return `{ok:false}` with the loader error;
  do not leave a half-prepared master.
- If the save/probe loop exhausts its retries, return `{ok:false, blob_ready:false}`
  with the last transient error, rather than reporting a ready master that is not.
- Non-Ozone or empty master with a successful load is a normal `"loaded"` path, not
  an error.

## Testing

**Unit (`master_ozone_utils`), offline, exhaustive over the plan cases:**
- empty master -> `load_required=True`, `action="loaded"`, `disable_indices=[]`.
- only `Ozone 12` (on) -> `reused`, `target_index=its index`, no disables.
- only `Ozone 12` (off) -> `reused_reenabled`.
- only older (`Ozone 10`) -> `loaded` + `disable_indices=[that index]`.
- mixed older + `Ozone 12` -> `reused`, older in `disable_indices`.
- multiple `Ozone 12` -> lowest index chosen as target.
- component-only trap: devices named `Ozone 12 Maximizer` / `Ozone 12 Equalizer`
  only -> MUST NOT match; treated as no Ozone (`loaded`).
- case/whitespace: names are matched exactly after strip; `"ozone 12"` lower-case is
  NOT a suite match (Live reports canonical `Ozone 12`).

**Executor / integration, live (manual, per repo convention):**
- reuse path against a master that already has Ozone 12 (returns `reused`,
  `blob_ready:true`).
- fresh-load path on a master without Ozone 12 (returns `loaded`, and the
  save-with-retry yields `blob_ready:true`).
- older-Ozone-present path (older disabled, 12 present or loaded).
- untitled-set precondition error.
- end-to-end: `ensure_ozone_master` -> `apply_master(device_index=data.device_index)`
  succeeds without manual intervention.

## Out of scope (YAGNI)

- Chain-order / module-membership manipulation (not encoded in the blob anyway).
- Removing older Ozone (we disable, never delete - non-destructive).
- Auto-saving an untitled set under a generated name (precondition error instead).
- Wiring into the `/ableton:produce` skill copy - a follow-up once the tool ships.
