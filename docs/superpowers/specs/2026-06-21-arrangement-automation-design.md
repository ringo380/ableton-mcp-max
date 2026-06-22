# Arrangement Timeline Automation - Design

**Date:** 2026-06-21
**Issue:** #30 (Arrangement timeline automation: write parameter envelopes bound to timeline position)
**Status:** Approved

## Problem

There is no MCP path to write **arrangement timeline automation** - breakpoint envelopes drawn
against the Arrangement timeline for device parameters, mixer params, or rack macros. The LOM
exposes automation only through `clip.automation_envelope(param)`, which **returns None for
Arrangement clips** (confirmed in the Live 11 API doc and live on Live 12.4). Session-clip
envelopes do not survive `duplicate_clip_to_arrangement`. There is no track-level breakpoint-write
API. So a producer cannot author a filter sweep into a drop, a send swell into a break, or a
volume fade tied to arrangement position.

## Feasibility (spiked 2026-06-21)

The `.als` set file is gzipped XML. Arrangement automation for a parameter is stored as one
`<AutomationEnvelope>` inside the owning **track's** `<AutomationEnvelopes><Envelopes>` list
(NOT inline on the parameter; the inline `<ArrangerAutomation>` holds only the manual/sentinel
value). Ground-truth structure, captured by a save-diff of a user-drawn Volume automation:

```xml
<AutomationEnvelopes>
  <Envelopes>
    <AutomationEnvelope Id="0">
      <EnvelopeTarget>
        <PointeeId Value="15838" />            <!-- = the param's <AutomationTarget Id> -->
      </EnvelopeTarget>
      <Automation>
        <Events>
          <FloatEvent Time="-63072000" Value="0.0005011872854" />   <!-- sentinel: pre-roll value -->
          <FloatEvent Time="0"  Value="0.0005011872854" />
          <FloatEvent Time="8"  Value="0.3162277937" />
          <FloatEvent Time="16" Value="1.99526238" />               <!-- Time=beats, Value=native units -->
          ...
        </Events>
        <AutomationTransformViewState>
          <IsTransformPending Value="false" />
          <TimeAndValueTransforms />
        </AutomationTransformViewState>
      </Automation>
    </AutomationEnvelope>
  </Envelopes>
</AutomationEnvelopes>
```

Confirmed facts:
- **Linkage:** `PointeeId` = the target parameter's `<AutomationTarget Id="N">`. Navigate to the
  param element, read its Id, reference it from the envelope.
- **Time** is in beats; **Value** is the parameter's native units (for a device param this is the
  raw float in `[Min, Max]`; v1 does not cover Volume's dB-curve mapping).
- **FloatEvent `Id` attributes are optional** - Live 12 writes them, Live 11 sets omit them and
  load fine. We omit them and let Live regenerate.
- The `<AutomationEnvelopes><Envelopes />` container already exists (empty, self-closing) on every
  track, so we populate it rather than create the parent.
- `AutomationEnvelope Id` is unique within a track's `<Envelopes>` list (start at 0, or max+1 if the
  list already has entries, e.g. the master's tempo/time-signature defaults).

### Reload mechanism (spiked)

The LOM has no "reload set" call. Live's control surface **re-initializes cleanly on every set
load** (verified in `Log.txt`: each load = `disconnect` -> `init` -> rebind 9877 -> fresh
`self._song = self.song()`). Therefore loading a patched `.als` by any means refreshes the MCP's
view - **no Remote Script change is required** (the cached `self._song` is not a bug; it is
re-set on each re-init).

- **In-place reload works** and avoids a full app relaunch: ⌘N (new Live set, closes the current
  one) then `open <path>` (loads the patched file). Verified: a track renamed on disk read back
  through the LOM after an in-place reload (~5s, vs ~15s for a relaunch).
- A bare `open` of the **already-open** set does NOT reload it (Live just focuses it); the ⌘N step
  is required to close it first.
- The reload briefly invalidates `self._song` (one MCP call returns a `None.None(Song)` C++
  signature error); it self-heals on the next call. The tool absorbs this with a short settle +
  one retry.

### Gotchas baked into the design

- **Named-set requirement:** the patch+reload needs a real `.als` on disk. `save_set` cannot save
  an Untitled set (its panel has no scriptable Save button). The tool errors clearly if the set is
  Untitled, instructing the user to `save_set_as` first.
- **iCloud staleness:** project folders under iCloud Drive can serve Live a stale copy on open. The
  tool operates on the actual on-disk path returned by `save_set` and gzips in place; if iCloud
  skew is observed in live testing, document it (a non-iCloud save location is the workaround).
- **Instrument-required-for-lane (UI):** Live only shows a track's automatable lanes in the UI when
  the track has a device. The XML references the param's AutomationTarget directly, so injection
  does not depend on the UI; live testing must confirm an injected envelope loads on a track that
  has the target device (device params always have a host device by definition).

## Scope

**v1: device parameters + rack macros only.** Native value units, so no Volume dB-curve mapping.
Covers the issue's device-sweep use cases (filter cutoff into the drop, etc.). Mixer
volume/pan/sends are a deliberate **follow-up** (they need the LOM-normalized <-> als-native value
conversion).

Out of scope for v1: mixer params (volume/pan/sends), BoolEvent/EnumEvent (on-off and quantized
parameters), reading arrangement automation back (the LOM cannot, and parsing it from the saved
`.als` is a separate read tool).

## Architecture

Mirrors the existing preset-patch backdoor (`preset_patch.py` + `*_preset_utils.py`): pure XML
logic in a `*_utils.py` module imported by `server.py` only; the Remote Script is untouched.

### New module: `ableton_mcp_max/als_automation_utils.py` (pure, unit-tested)

Responsibilities (no Live dependency):
- `read_als(path) -> str` / `write_als(path, xml)` - gzip decode/encode of the `.als`.
- **Navigator:** locate a track's block in the XML by track index (Nth `<Track>`/`<MidiTrack>`/
  `<AudioTrack>` under `<Tracks>`), then within it locate the target device (Nth device in the
  track's device chain) and the named/indexed parameter element, returning its
  `<AutomationTarget Id="N">` value. Depth-aware, anchored on the track block (never the first
  global match) - same discipline as `rack_preset_utils`.
- **Macro resolution:** a rack macro maps to its `MacroControls.<i>` element (and its
  AutomationTarget Id) within the rack device.
- `build_envelope_xml(pointee_id, points, env_id) -> str` - render the `<AutomationEnvelope>` block
  (sentinel + sorted FloatEvents + the `AutomationTransformViewState` boilerplate). Times in beats,
  values clamped to the param's `[Min, Max]` if known.
- `inject_envelope(xml, track_index, pointee_id, envelope_xml, replace) -> str` - insert the
  envelope into the track's `<Envelopes>` list, allocating a fresh `AutomationEnvelope Id`. With
  `replace=True`, remove any existing envelope for the same `PointeeId` first (idempotent rewrites).
- `points_to_events(points)` - normalize `[{time, value}]` to the event list, inserting the
  `-63072000` sentinel holding the first point's value, sorting by time, allowing duplicate times
  (vertical steps).

### Server: `set_arrangement_automation` tool

```
set_arrangement_automation(
  lanes=[{track_index, device_index, parameter, points:[{time, value}], replace=true}, ...],
  reload=true,
) -> JSON
```

- `parameter` accepts a name or index (matching `get_device_parameters` / `set_device_parameter`).
- One call may carry many lanes; the patch is applied to a single `.als`, then ONE reload.
- Steps: resolve set path (error if Untitled) -> `save_set` -> `read_als` -> for each lane:
  resolve the param's AutomationTarget Id via the navigator, build + inject the envelope ->
  `write_als` -> in-place reload (helper) -> settle + verify the set reloaded.
- Returns per-lane `{track_index, device_index, parameter, pointee_id, points_written, ok}` plus
  the set path and reload status.

### Reload helper: `_reload_set(path, set_name)` in server.py

Analogous to `_restart_live_impl` but in-place (no quit): activate Live -> ⌘N (handle a save
dialog defensively with ⌘D, though a just-saved set is clean) -> `open <path>` -> wait for the
front window title to equal the set name and for the first MCP call to succeed (absorbing the
one-shot stale-`self._song` error). No app relaunch.

## Data flow

```
set_arrangement_automation(lanes)
  -> get set path (Untitled? -> error)
  -> save_set                          (Live writes current state to disk)
  -> read_als(path)                    (gunzip -> xml)
  -> for lane in lanes:
       navigate track[i] -> device[j] -> param -> AutomationTarget Id
       build_envelope_xml(id, points)
       inject_envelope(xml, ...)
  -> write_als(path, xml)              (gzip)
  -> _reload_set(path)                 (Cmd-N + open, in-place)
  -> verify reloaded (settle + retry)
  -> return per-lane results
```

## Error handling

- Untitled set -> `_err` instructing `save_set_as` first.
- Track/device/parameter not found in the XML -> per-lane `ok:false` with the reason; other lanes
  still apply (the whole patch is one file write, so resolution happens before the write; a lane
  that fails to resolve is reported and skipped, the rest are written).
- `save_set` failure (e.g. Live not frontmost / no Accessibility) -> surfaced, no patch attempted.
- Reload failure (window title never matches) -> report `reloaded:false`; the patch is on disk and
  will load on the next manual open.
- Malformed-XML guard: re-parse the injected envelope region after write; abort if the gzip
  round-trip fails.

## Testing

- **Offline pure tests** (`tests/test_als_automation_utils.py`): navigator resolves a param's
  AutomationTarget Id from synthetic + real-file fixtures; `build_envelope_xml` shape (sentinel,
  sorting, duplicate times, clamping); `inject_envelope` populates an empty `<Envelopes />` and
  replaces an existing same-PointeeId envelope; gzip round-trip. Real-file round-trip gated with
  `skipif` on a sample `.als` (the macro-mapping pattern from `rack_preset_utils` tests).
- **Offline gate:** `uv run --with pytest pytest -q`, `import ableton_mcp_max.server`,
  `py_compile` the Remote Script (unchanged, but keep the gate green).
- **Live round-trip:** load a scratch set with a device, `set_arrangement_automation` a device
  param across several beats -> in-place reload -> re-save -> confirm the `<AutomationEnvelope>`
  Live wrote back matches (proves Live accepted it into its model) and the param moves over the
  arrangement.

## Docs / packaging

- New tool in the **Composition** category (sibling to `set_automation`); regenerate
  `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md`, and hand-edit the 5 hardcoded
  counts in `docs/index.md`. Tool count 145 -> 146.
- `als_automation_utils` is imported by `server.py` only (the Remote Script cannot import it).
- Version bump to the next minor; release + marketplace ref bump per the standard flow.

## Follow-ups (not v1)

- Mixer volume/pan/sends (needs LOM-normalized <-> als-native value conversion; Volume is a
  log/dB curve).
- BoolEvent / EnumEvent for on-off and quantized device params.
- A read tool that parses arrangement automation back out of the `.als` (the LOM cannot read it).
- Optional: fold the in-place `_reload_set` helper into a general capability other file-backdoor
  tools can reuse.
