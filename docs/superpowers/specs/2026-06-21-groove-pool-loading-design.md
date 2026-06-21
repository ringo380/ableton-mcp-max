# Groove Pool Loading — Design

**Created**: 2026-06-21
**Status**: In Progress
**Issue**: #36 (follow-up to #27 groove/swing, shipped v0.15.0)

## Overview

`assign_groove_to_clip` (v0.15.0) binds a Groove-Pool groove to a clip, but only
works on grooves *already* in the pool. There is no MCP path to ADD a groove to
the pool, so the user must drag an `.agr` into Live's Groove Pool by hand first.

This work adds **`load_groove_to_pool(name_or_path)`** — making a factory or
User-Library groove appear in `get_groove_pool` — plus a companion
**`search_grooves(query, limit)`** for discovery. Closes the
generate → groove → assign loop with no manual drag.

## Feasibility (spike, PROVEN live on Live 12.4, 2026-06-21)

Confirmed dead ends:
- **No LOM path:** `GroovePool`/`Groove` classes expose no create/load/add
  method; `grooves` is read-only.
- **No "Grooves" browser category** — `.agr` cannot be browser-loaded directly.

The working mechanism — **`.alc` clip-embed backdoor** (proven: pool went 1→2,
new groove assignable):
1. An `.alc` (Live Clip) is gzipped XML `<Ableton><LiveSet>` carrying a
   `<GroovePool><Grooves>` block + a clip whose `<GrooveSettings><GrooveId Value="N">`
   references a pool groove.
2. A factory `.agr` is plain (un-gzipped) XML `<Ableton><Groove><Name><Clip><Value><MidiClip>`.
   Its `<Groove>` inner maps into `<GroovePool><Grooves><Groove Id="N">` (drop the
   Groove-level `<LomId>`, add `Id`).
3. Inject the groove, set the clip's `GrooveId` + `DefaultGrooveId` = N, gzip,
   write to `<UserLibrary>/Clips/<name>.alc` (auto-indexed,
   `query:UserLibrary#Clips:<name>.alc`).
4. `load_browser_item {track_index, item_uri}` → Live MERGES the embedded groove
   into the project Groove Pool. The groove persists after the carrier track/clip
   is removed.

### Spike-discovered gotchas (drive the design)
- **Schema-version mismatch:** factory `.agr` are Live 11 (`MinorVersion 11.0_423`);
  their MidiClip carries cosmetic nodes (`ScaleInformation`, `IsInKey`,
  `NoteSpellingPreference`, `PreferFlatRootNote`, `NoteEditorFold*`) that a Live-12
  LiveSet (`MinorVersion 12.0_12402`) rejects → load fails *"is corrupt … Unexpected
  value for int node: Major"*. **Fix: strip those cosmetic nodes** (safe for both
  versions; they are not groove-defining). Wrapper header `MinorVersion` must match
  the running Live version.
- **Device pollution:** loading a factory *melodic* `.alc` wrapper dragged in its
  instrument (renamed the carrier track). **Fix: device-less minimal wrapper**
  (empty `<DeviceChain>`, tiny empty MIDI clip).
- **Track side-effect:** `load_browser_item` targets a track + drops a clip in a
  slot. **Orchestration: create scratch MIDI track → load → delete scratch track**
  (pool groove persists — desired).
- Pool grooves **cannot be removed via LOM** (read-only) — once added they persist
  until the user removes them by hand or doesn't save.

## Architecture

Follows the repo's existing **preset-patch backdoor** pattern (pure XML logic in a
`*_preset_utils.py` module, server-only, unit-tested; Remote Script unchanged).

- **`groove_preset_utils.py`** (NEW, pure, server-only):
  - `resolve_groove_source(name_or_path, factory_root, user_library)` → `.agr` path
    (single match) or a structured multi/no-match error.
  - `agr_to_pool_groove(agr_xml, groove_id=0)` → `<Groove Id="N">…</Groove>` string,
    cosmetic nodes stripped, `<Name>` preserved.
  - `build_groove_carrier_alc(wrapper_xml, groove_entry, groove_id=0)` → device-less
    `.alc` LiveSet XML with the groove injected + clip `GrooveId`/`DefaultGrooveId` wired.
  - `groove_pool_name(agr_xml)` → the internal `<Name>` (what the pool will display).
  - `list_grooves(factory_root, user_library, query, limit)` → name/category/path rows.
- **`server.py`** (host orchestration, reuses existing helpers
  `_user_library_dir`, `_app_core`/version-detect, `_write_user_preset`-style write,
  scratch-track create/delete, `load_browser_item` send):
  - `load_groove_to_pool(name_or_path)` and `search_grooves(query, limit)` `@mcp.tool`s.
- **Remote Script:** NO new handler — reuses `load_browser_item`, `create_midi_track`,
  `delete_track`, `get_groove_pool`.

### `load_groove_to_pool` flow
1. Resolve source `.agr`.
2. `get_groove_pool` → if the groove's pool name already present, return
   `{ok, already_present: true, groove_name, pool_index}` (skip — avoids Live's
   `Name (2)` duplicates).
3. Build device-less carrier `.alc` (version-matched header) → write to
   `<UserLibrary>/Clips/<temp>.alc`.
4. Create scratch MIDI track → `load_browser_item` the carrier → delete scratch track.
5. Delete the temp `.alc`. Re-read `get_groove_pool`, locate the new groove.
6. Return `{ok, groove_name, pool_index, source, pool_count}`.

### Tool signatures
```
load_groove_to_pool(name_or_path: str) -> str
    # name (factory/User .agr stem, case-insensitive) or .agr path.
    # Skips if already in pool. Returns pool name + index for assign_groove_to_clip.

search_grooves(query: str = "", limit: int = 50) -> str
    # Lists factory (Core Library/Grooves/**) + User-Library .agr by name/category.
```

## Files to Modify
- `ableton_mcp_max/groove_preset_utils.py` — NEW pure module (transform + resolve + list).
- `ableton_mcp_max/server.py` — add `load_groove_to_pool` + `search_grooves` tools.
- `tests/test_groove_preset_utils.py` — NEW unit tests.
- Docs/version: `pyproject.toml` + `.claude-plugin/plugin.json` → v0.16.0, `uv lock`,
  regen tool index/docs (141 tools), hand-edit `docs/index.md` hero counts, PROGRESS.md.

## Error Handling
- Multi-match name → error listing candidate names (caller disambiguates).
- No match → error with closest names.
- Missing/unreadable `.agr` → error.
- Live version unresolved → default to stripping cosmetic nodes (safe for 11 & 12).
- Load timeout/failure → surface Live's message; clean up the temp `.alc` + scratch
  track in a `finally` so a failure leaves no residue.

## Testing / Verification
- **Pure unit tests** (offline `uv run pytest`): `.agr`→pool-groove transform,
  cosmetic-node stripping (timing/`<Notes>` preserved), device-less wrapper assembly +
  `GrooveId` wiring, version-header selection, name resolution (single/multi/none).
  Include a **real factory `.agr` round-trip** test `@pytest.mark.skipif` (use
  `re.DOTALL`; one-line synthetic fixtures hide multi-line bugs).
- **Offline gate:** `pytest` + `py_compile remote_script` + `import ableton_mcp_max.server`.
- **Live verification** (manual, → PROGRESS.md): empty-pool set → `search_grooves` →
  `load_groove_to_pool` → pool grew → `assign_groove_to_clip` the new groove → confirm.
- **Restart:** Claude Code restart only (new server.py tools + new pure module). No
  Remote Script reinstall, no Live bounce.

## Groove-Pool Removal — feasibility (runtime-probed, DEFINITIVE)

A temporary Remote Script introspection handler was run against the live Live 12.4
`GroovePool` (the "doc is wrong" approach that previously found `clip.groove` is
settable). Findings — removal is **genuinely infeasible**, runtime-enforced, not a
doc artifact:
- `GroovePool` runtime surface = `grooves` + listeners only; **no `delete_groove`/
  `remove_groove`** (`AttributeError`).
- `grooves` is a Live **`Vector`** whose `dir()` shows `append`/`extend`, but the
  container is **read-only at runtime**: `del grooves[i]` → `RuntimeError: Cannot
  modify read only container`. `grooves.remove` → no attribute.
- `Groove` has **no `delete`** method. It DOES expose settable feel params:
  `base`, `timing_amount`, `random_amount`, `velocity_amount`, `quantization_amount`,
  `name`.
- The `.alc` file backdoor only **merges (adds)** into the open project's pool; it
  cannot subtract. `undo` removes a just-added groove but is global/destructive
  (scrambles track types) — not a usable targeted-removal lever.

**Decision — handle the "no removal" gap via:**
1. **Skip-on-duplicate** (designed above) — the primary clutter-prevention; repeated
   `load_groove_to_pool` / produce runs never multiply pool entries.
2. **Clear docstrings**: `load_groove_to_pool` states the only true removal is manual
   (right-click → Remove in Live's Groove Pool), and that a discarded/unsaved set
   drops added grooves.
3. **Soft-delete option (deferred, not in v1):** because `Groove.timing_amount` /
   `random_amount` / `velocity_amount` are settable, an unwanted groove can be
   *neutralised* (all amounts → 0) so it has zero audible effect while remaining a
   harmless pool entry. Revisit only if clutter proves a real problem in practice.

## Out of Scope (YAGNI)
- Creating grooves from scratch / editing groove timing.
- **Removing grooves from the pool — runtime-confirmed infeasible** (read-only
  container, no delete method); handled via skip-on-duplicate + docs, not a tool.
- Max for Live path (the file backdoor works for adds; the same read-only container
  blocks Max-side removal too — verified surface is identical).
