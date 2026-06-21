# Groove & Swing for Generated Clips — Design

**Created**: 2026-06-20
**Status**: Phase 0 resolved (groove assignment FEASIBLE via Python); Phases 1-2 implemented
**Issue**: #27 (Groove/swing automation: assign groove-pool swing to clips for playback)

## Outcome (2026-06-21)

The Phase 0 spike **overturned the get-only assumption**: Live 12's embedded Python honors
`Clip.groove = pool.grooves[i]` - it does not raise and genuinely changes the clip's groove
(proven by a reversible A->B->A round-trip on a scratch clip, each change confirmed on a separate
read). `clip.groove = None` raises an `ArgumentError` whose C++ signature requires a real groove
handle, which both blocks clearing-via-None and confirms the setter is a genuine type-validated
binding (not a no-op). So Phase 2 ships on the pure-Python path - **no Max device, no `.alc`
backdoor**. Shipped tools: `swing_clip` (Phase 1), `assign_groove_to_clip` + `get_groove_pool`
(Phase 2). Remaining open item: populating the Groove Pool from a factory `.agr` via MCP - grooves
are not exposed in the LOM browser, so assignment works only on grooves already in the pool.

## Overview

Generated MIDI parts (basslines, drums, melodies) come out rhythmically straight. There is
currently no way to give an existing clip a swung/shuffled feel:

- `set_swing_amount` sets the *global* swing applied to **future** quantize/add operations. It does
  not retroactively swing notes already in a clip and is not how Live swings playback.
- `set_groove_amount` scales how strongly an **assigned** clip groove is applied — but there is no
  tool to assign a groove from the Groove Pool to a clip, so the amount has nothing to act on.

This work delivers a real, non-faked swing path that ships immediately, and runs a feasibility
spike to determine whether true Groove-Pool assignment is reachable outside the Python LOM (via
Max for Live or an `.alc` file backdoor) before committing to an assignment tool.

## LOM feasibility (already checked)

Against `Live_API_Doc/11.0.0.xml`:

- `Clip.groove` → *"**Get** the groove associated with this clip"* — get-only descriptor. By the
  project convention (a doc reading "Get" with no "Set" is read-only), the **Python** LiveAPI does
  not allow assigning a groove to a clip.
- `Clip.has_groove` → read-only.
- `GroovePool.grooves` → read-only list. No `load_groove` / `create_groove` / `add_groove` method
  exists anywhere in the API; no `.agr` file-load entry point.
- `Groove.{base, quantization_amount, random_amount, timing_amount, velocity_amount, name}` are
  settable — but only for a groove that *already exists* in the pool, and binding it to a clip is
  still the missing piece.

**Conclusion:** assignment is infeasible *via the Python LOM property*. It is **not** confirmed
infeasible overall — the Python doc is auto-generated from Python descriptors and is not the full
Live API surface. Phase 0 tests the two avenues the Python doc cannot speak to.

## Phases

### Phase 0 — Groove-assignment feasibility spike (decision gate)

Runs first; its outcome selects the Phase 2 approach. Requires Live open; run live via the
`AbletonDev` (working-tree) MCP.

- **Sub-probe A — pool population.** Test whether `load_browser_item` of a factory `.agr` groove
  populates the Groove Pool. Browser-load is a separate mechanism from the read-only
  `GroovePool.grooves` list. A groove must exist in the pool before assignment can be tested.
- **Sub-probe B — Max LiveAPI assignment.** Build a minimal M4L LiveAPI probe device: point a
  `live.object` at the target clip and issue `set groove <pool_id>` plus `call`-style variants.
  Max reaches Live's C++ objects through a different access path than Python and may permit a `set`
  the Python descriptor restricts. Report success/failure over the existing node-bridge.

**Decision gate:**
- Max `set groove` works → Phase 2 assignment tool rides the Max path (and the general
  Max-automation door is open for future work).
- Max path fails → reverse the `.alc` groove XML via save-diff and build the file-based backdoor
  (Phase 2, `.alc` variant).
- Either outcome is documented honestly in Phase 3.

This phase is exploratory; its only hard deliverable is a recorded verdict (and the probe device
if Max works). It does **not** block Phase 1.

### Phase 1 — Swing-baking note tool (ships independently of Phase 0)

A real, non-faked swing applied to notes already in a clip.

- **Tool:** `swing_clip(track_index, clip_index, amount, grid="1/16", track_type="regular")`
  (final signature in the plan). Shifts off-beat notes later on the chosen grid by the resolved
  swing fraction. Undo-able via the global `undo`.
- **Grid:** `"1/8"` or `"1/16"`. Off-beat = grid positions at odd step indices; on-beats are left
  in place. Notes are snapped to the nearest grid step to classify on/off-beat (configurable
  tolerance), so already-quantized generated parts behave predictably.
- **Amount (handles both input styles gracefully):** a pure resolver in `groove_utils.py` maps the
  single `amount` arg to a canonical swing fraction in `[0, 1]` (0 = straight, 1 = off-beat lands
  on the next on-beat):
  - `amount > 1.0`, or a string like `"66%"` → MPC-style percent: `fraction = (percent - 50) / 50`,
    clamped to `[0, 1]`.
  - `amount` in `[0.0, 1.0]` → direct fraction, used as-is.
  - Ranges do not overlap (`60` is unambiguously percent, `0.3` unambiguously a fraction).
- **Timing math:** for an off-beat note at grid time `t` with step length `s`, new start =
  `t + fraction * (s / 2)`. At `fraction = 1` the off-beat is delayed by half a step (its maximum
  shuffle, landing halfway toward the next grid step — MPC 75%); at `fraction = 0` it is unchanged.
  Math is pure and unit-tested.
- **Architecture:** `groove_utils.py` (imported by server.py only) holds `resolve_swing(amount)`,
  grid→step resolution, and `compute_swung_starts(notes, step, fraction, tolerance)`. The handler
  reads via `get_notes_extended`, applies new start times in place by `note_id` via
  `modify_clip_notes` (no legacy modal/stall), and re-reads to confirm.
- **Optional convenience (YAGNI-gated):** named presets ("8th swing 60%", "16th swing 66%") only if
  trivial; otherwise omit.

### Phase 2 — Groove assignment tool (shape set by the Phase 0 gate)

- **Max path:** `assign_groove_to_clip(...)` driving the M4L LiveAPI probe-turned-tool, plus a
  pool-population helper (load `.agr` via browser). `set_groove_amount` becomes meaningful.
- **`.alc` backdoor path:** patch generated notes + an embedded groove + its assignment into an
  `.alc` (gzipped XML, same family as our preset backdoor), load via browser onto the slot. Pure
  XML logic in a `*_utils.py` module on the shared preset-patch core.

Detailed design deferred until Phase 0 resolves; the plan will branch here.

### Phase 3 — Documentation

- `/ableton:best-practices`: what swing/groove operations are and are not possible.
- `/ableton:produce`: replace the inline "limitation" note with the real swing option (and the
  groove verdict).
- Tool docstrings: honest about scope.
- Regenerate tool index/docs (`scripts/gen_docs_site.py`, `scripts/build_tool_index.py`) and the
  hardcoded counts in `docs/index.md` on any net tool-count change.

## Files to Modify / Create

- `ableton_mcp_max/groove_utils.py` — NEW: `resolve_swing`, grid→step, `compute_swung_starts`.
- `ableton_mcp_max/server.py` — NEW `@mcp.tool() swing_clip`; Phase 2 assignment tool(s).
- `remote_script/AbletonMCP/__init__.py` — handler branch(es) for the swing apply (and Phase 2 if
  Max path needs a handler relay).
- M4L LiveAPI probe device + node-bridge wiring (Phase 0/2, Max path only).
- `tests/test_groove_utils.py` — NEW: resolver (both input styles + clamp edges), grid math,
  swung-start computation.
- Docs/commands as in Phase 3.

## Testing & Verification

- Offline: `uv run --with pytest pytest -q` for `groove_utils` (pure logic); `py_compile` the
  handler; import-check the server.
- Live (manual, via `AbletonDev`): Phase 0 spike verdict; Phase 1 swing applied to a scratch clip
  (read notes back, confirm off-beats moved and on-beats did not); restore/undo after.
- Record results + the Phase 0 verdict in `PROGRESS.md`.

## Open Questions / Risks

- Phase 0 Max path is genuinely uncertain — it may fail, in which case Phase 2 falls to the `.alc`
  backdoor (more work) or is deferred to a follow-up issue.
- Classifying on/off-beat for non-quantized or triplet-based clips needs a sane tolerance default;
  document the assumption (works best on grid-quantized parts).
