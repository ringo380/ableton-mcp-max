# render_audio - Design

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Author:** ableton-mcp-max

## Goal

One MCP tool, `render_audio`, that bounces the current set's Main output to an
audio file on disk - format, bit depth, sample rate and render range under
program control - and returns the resolved path. This closes the last gap in the
`/ableton:produce` pipeline: the MCP can compose, arrange, mix and master a
track but cannot currently deliver a file.

## Motivation

There is no export, render, bounce, freeze or flatten tool in the 185-tool
surface, and the LOM exposes none of them (confirmed against the Live 11 API doc:
zero hits for `export`, `render`, `bounce`, `freeze`, `flatten`). Rendering is a
menu + dialog operation only. Everything downstream of mastering - auditioning
the bounce, loudness-checking the actual file, handing the user a deliverable -
is currently a manual step.

## Live-verified findings (de-risk spike, 2026-07-13, Live 12.4.2)

Driven against a real set. All of the following are OBSERVED, not assumed.

1. **The Export dialog is a real, fully AX-addressable dialog.** `File > Export
   Audio/Video` opens window `Export Audio/Video` (`role=AXWindow`,
   `subrole=AXDialog`) holding ONE `AXGroup` with 49 children.
2. **Every control is addressable by its AX `description`** (titles are all
   `missing value`; descriptions are stable):
   - Popups: `Rendered Track Chooser`, `Sample Rate`, `File Type`,
     `Recording Bit Depth`, `Dither Options`, `Choose Video Encoder`.
   - Toggles (`AXButton`, value `On`/`Off`): `Include Return and Main Effects`,
     `Render as Loop`, `Convert to Mono`, `Normalize`, `Create Analysis File`,
     `Encode PCM`, `Encode MP3`, `Create Video with Rendered Audio`.
   - Action buttons: `Export`, `Cancel`, `Edit`.
3. **Toggles respond to `click`** - verified Normalize Off -> On -> Off. `click`
   TOGGLES; it does not set. A blind click inverts an already-correct control.
4. **`Export` and `Cancel` are real `AXButton`s exposing `AXPress`** - verified
   (Cancel closed the dialog). This is UNLIKE Live's Save panel, which has no
   pressable buttons. The "Ableton dialogs have no AX buttons" rule does NOT
   apply to the Export dialog.
5. **The Render Start / Render Length sliders are NOT settable, by ANY means.**
   `set value of slider ... to 5.0` returned success but the value stayed at
   `7.0` (the silent `AXSetValue` no-op), AND a click-then-type-then-Return into
   the number box also left it unchanged. Start and Length are each three
   sliders (`Start of Rendered Sample (Bar)` / `(Beat)` / `(Sixteenths)`, and
   the `Length of Rendered Sample (...)` trio). The range CANNOT be driven
   through the dialog - it must be established before the dialog opens.
6. **The dialog seeds its range from the ARRANGEMENT TIME SELECTION, not the
   loop brace.** Setting the loop via the LOM alone does NOTHING: with
   `loop=true, start=16, length=32` confirmed by `get_transport`, the dialog
   still opened at `Start = bar 7, Length = 0` - bar 7 being exactly the
   playhead (`current_song_time = 24.0` beats). So Start follows the playhead
   and Length follows the time selection (0 when nothing is selected).
7. **`Edit > Select Loop` converts the loop brace into a time selection, and
   THAT seeds the dialog** - verified: loop `start=16 (bar 5), length=32 (8
   bars)` -> `Select Loop` -> dialog opened at `Start = bar 5, Length = 8 bars`.
   This is the range mechanism.
8. **`Select Loop` is Arrangement-only** - it is DISABLED while Live is in
   Session view, so the Arrangement view must be focused first. The View menu
   only offers `Toggle Arrangement/Session View` (a toggle, not a setter), so
   the view must be set deterministically through the LOM:
   `Application.View.is_view_visible("Arranger")` / `show_view` / `focus_view`
   all exist in the API. This needs a new Remote Script handler.
9. **A menu item's `enabled` state is only valid after its menu has been
   OPENED** (macOS validates on menu-open). Reading `enabled of menu item ...`
   cold returns a stale `false`. Click the menu bar item first, then read.
10. **After `Export`, an NSSavePanel appears** (window `Save`, `subrole=AXDialog`)
    with only close/zoom/minimize buttons and no top-level text field - the same
    panel shape `save_set` already handles. Confirm = type the name, press Return.
11. **The render lands in Live's LAST-USED export directory**, which is not
    introspectable and is NOT the project folder. On the dev machine the spike's
    file landed in the iCloud Drive root
    (`~/Library/Mobile Documents/com~apple~CloudDocs/`).
12. **Both dialogs close when the render completes** - a window-state poll is a
    valid completion signal.
13. Spike output verified: a 24-bit / 44.1 kHz stereo WAV of exactly the requested
    0.125 s range, plus (because `Encode MP3` was On) an MP3, plus `.asd` analysis
    sidecars for each.
14. The File menu item is exactly `Export Audio/Video...`; `Edit` also exposes
    `Freeze Track`, `Bounce Track in Place`, `Bounce to New Track` (a future
    freeze/flatten tool is feasible by the same mechanism).

## Architecture

Repo-standard pure-resolver + thin-executor split (as in `master_ozone_utils.py`
+ the `ensure_ozone_master` executor).

### Remote Script: new `focus_view` handler

`remote_script/AbletonMCP/__init__.py` gains a `focus_view` command. `show_view` /
`focus_view` are WRITES into Live's UI state, so it is a MUTATION: listed in the
`elif command_type in [...]` dispatch and handled on the main thread (`_focus_view`),
like every other mutation:

```python
# view = "Arranger" | "Session"
app = Live.Application.get_application()
if not app.view.is_view_visible(view):
    app.view.show_view(view)
app.view.focus_view(view)
```

Exposed as a small `focus_view(view)` MCP tool (useful on its own), and called by
`render_audio` before `Select Loop`. Keep it Py2/3.7-safe (no f-strings).

### `ableton_mcp_max/export_utils.py` (new, pure, unit-tested)

No I/O. Validates and normalizes the caller's options into a plan keyed to the
dialog's real AX description strings.

- `plan_export(file_type, bit_depth, sample_rate, normalize, mp3, mono,
  include_returns, analysis_file, dither)` ->
  `{"popups": [{"description": ..., "value": ...}, ...],
    "toggles": [{"description": ..., "want": "On"|"Off"}, ...]}`
- Enum validation with clear errors (never send an unknown value to a popup):
  - `file_type`: `WAV`, `AIFF`, `FLAC`, `MP3`
  - `bit_depth`: `16`, `24`, `32`
  - `sample_rate`: `44100`, `48000`, `88200`, `96000`, `176400`, `192000`
  - `dither`: `No Dither`, `Triangular`, `Rectangular`, `POW-r 1/2/3`
- **Format reconciliation.** `file_type="MP3"` means PCM off + MP3 on;
  `mp3=True` alongside a PCM `file_type` means BOTH files are emitted (Live's
  actual behavior, observed in the spike). The resolver makes this explicit
  rather than letting the dialog's sticky state decide.
- `clean_render_name(name)` - reject `/` and `:` (they hijack the save panel's
  Go-to-Folder), reject empty. Mirrors `save_utils.clean_set_name`.
- `loop_range_for(start_bar, end_bar, song_length, sig_num)` ->
  `(start_beats, length_beats)`. Bars are 1-based as Live displays them, so
  `bar N` starts at `(N - 1) * sig_num` beats. Both `None` -> the whole song
  (`0`, `song_length`). Raises on `end_bar <= start_bar`, on a negative or
  zero-length span, and on a `song_length` of 0 (nothing to render).
  The executor sends the resulting beats to `set_arrangement_loop`, and reuses
  the same numbers to VERIFY the dialog's seeded bar/length.

### `render_audio` executor in `server.py` (new `@mcp.tool()`)

Signature:
`render_audio(ctx, name, start_bar=None, end_bar=None, file_type="WAV",
bit_depth=24, sample_rate=44100, normalize=False, mp3=False, mono=False,
include_returns=True, analysis_file=True, dither="No Dither", timeout=600.0)`

Steps:
1. Fail fast if no Live is running (`_live_app_and_pid`, as `_save_as_impl` does).
2. **Establish the render range BEFORE opening the dialog** (findings 5-8; the
   sliders cannot be written at all). Three ordered steps:
   a. Set the arrangement loop over the target range via the LOM. Default (no
      `start_bar`/`end_bar`) = the whole song: loop `start=0`,
      `length=song_length` from `get_transport`.
   b. Focus the Arrangement view via the new Remote Script `focus_view` handler
      (`Select Loop` is disabled in Session view, and the View menu only
      toggles).
   c. Click `Edit > Select Loop`, turning the loop into the time selection that
      the dialog reads.
3. Open the dialog with `_click_file_menu("Export Audio/Video...")` -
   focus-independent, unlike a Cmd-key keystroke. Wait for the
   `Export Audio/Video` window; error out if it never appears (Accessibility
   permission / locked screen), exactly as `_save_as_impl` reports.
   **Verify the dialog's seeded Start/Length match the requested range**, and
   Cancel + error on a mismatch - never silently render the wrong span.
4. **Apply toggles read-then-click:** read each toggle's current `On`/`Off` and
   click ONLY on a mismatch. Never blind-click (finding 3).
5. **Apply popups** via `AXPress` + pick the menu item by name.
6. **Verify the dialog state matches the plan.** Re-read every toggle and popup;
   on any mismatch, press `Cancel` and return `{ok:false}` - never export a
   chain we could not confirm.
7. Press `Export`, wait for the `Save` window.
8. Select-all + type the name, press Return (the `_save_as_impl` pattern).
9. **Poll for completion**: wait until BOTH the `Export Audio/Video` and `Save`
   windows are gone, bounded by `timeout` (a full-track render takes real time -
   never a fixed sleep).
10. **Resolve the output path** and return it.

### Path resolution

The directory is not controllable (finding 7), so the path is resolved AFTER the
render, best-effort, and the render is never failed for an unresolved path (the
`_find_saved_set` precedent).

- Resolve by name via Spotlight (`mdfind -name <basename>`), filtered to files
  modified after a timestamp captured before the export, and to the expected
  extension.
- **Do NOT use a `find ~ -not -path "*/Library/*"` walk.** iCloud Drive lives
  under `~/Library/Mobile Documents`, so that pattern silently misses the file -
  observed during the spike.

## Return shape

```
{ok: true, data: {
  name: <str>,
  path: <str|null>,        # null if Spotlight could not resolve it (not an error)
  extra_paths: [<str>],    # e.g. the MP3 when mp3=True alongside a PCM file_type
  bytes: <int|null>,
  duration_s: <float|null>,
  file_type: "WAV", bit_depth: 24, sample_rate: 44100,
  range: {start_bar: <int|null>, end_bar: <int|null>},
  rendered: true
}}
```

## Error handling

- No running Live -> `{ok:false}`.
- Export dialog never appears -> `{ok:false}` naming the Accessibility-permission
  cause (the `_save_as_impl` message).
- Bad enum / bad name -> `{ok:false}` from the pure resolver, BEFORE any UI is
  touched.
- Dialog state fails post-set verification -> press `Cancel`, `{ok:false}`.
- Render does not complete within `timeout` -> `{ok:false, rendered:false}` with
  the last-seen window state; do NOT claim a file.
- Path unresolved but render completed -> `{ok:true, path:null}` plus a note. The
  file exists; we just could not locate it.

## Testing

**Unit (`export_utils`), offline:**
- Each enum: valid values accepted, unknown value rejected with a clear error.
- `file_type="MP3"` -> Encode PCM Off + Encode MP3 On.
- `mp3=True` + `file_type="WAV"` -> both Encode PCM On and Encode MP3 On.
- Toggle plan carries an explicit `On`/`Off` want for every toggle it manages
  (so the executor can read-then-click rather than assume a default).
- `clean_render_name`: rejects `/`, `:`, empty; passes an ordinary name.
- `loop_range_for`: bar 1 -> beat 0; bar 5 with 4/4 -> beat 16; bars 5..13 ->
  `(16, 32)`; both `None` -> `(0, song_length)`; 3/4 signature honored;
  `end_bar <= start_bar` raises; `song_length == 0` raises.

**Executor, monkeypatched (no Live):**
- Toggles already correct -> NO clicks issued (the idempotency contract).
- Toggle mismatched -> exactly one click.
- Dialog never appears -> `{ok:false}`, no Export press.
- Post-set verification mismatch -> Cancel pressed, `{ok:false}`, no Export press.
- Completion poll times out -> `{ok:false, rendered:false}`.

**Live gate (manual, per repo convention):**
- **From SESSION view** (the case that broke the spike): render still works -
  the tool must focus Arrangement itself, not assume the user's view.
- Short range (a few bars) -> WAV appears on disk, path resolved, duration matches
  the requested range.
- Default (no range) -> renders the whole song (`song_length`).
- `mp3=True` -> both files reported.
- Re-run with identical options -> no toggle churn (state already correct).
- Bad name (`a/b`) -> rejected before the dialog opens.

## Out of scope (YAGNI)

- Per-track / stem export (the `Rendered Track Chooser`) - a follow-up.
- Video export (`Create Video`, `Choose Video Encoder`).
- Choosing the output DIRECTORY - not scriptable through the panel; we drive the
  name and resolve the path, exactly as `save_set_as` does.
- Freeze / Flatten (separate menu operations, separate tool).
