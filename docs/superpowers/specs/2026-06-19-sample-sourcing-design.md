# Sample sourcing

**Created:** 2026-06-19
**Status:** Design

## Summary

Sub-project **#4a** of the autonomous track production initiative (#0 master/return,
#1 composition, #2 arrangement intelligence, #3 closed-loop remediation,
**#4 `/ableton:produce` skill**). #4 grew large and was decomposed into **#4a sample
sourcing tools** (this spec - the new MCP tools the skill depends on) and **#4b the
`/ableton:produce` orchestration skill** (a separate, later spec).

Adds the ability to discover audio samples in Live's browser (factory + User Library)
and load them as audio clips, drum-rack one-shots, and full drum kits. Four new tools,
one new pure module, and an iCloud-materialization helper. All server-side; **no Remote
Script change is planned** unless the drum-pad feasibility spike forces the preset-patch
load path (decided at spike time).

## Motivation

After v0.12.0 the server can generate MIDI parts (#1), arrange them (#2), and mix/master
them (#3), but it cannot bring in **audio content**. Producing a real track needs samples:
drum one-shots, loops, and pre-built kits. The gaps:

- There is no way to **search** the browser by intent. `get_browser_items_at_path` lists
  only direct children of one path; finding "all the kick one-shots" means walking the
  tree by hand and overrunning the token limit (factory devices alone expose hundreds of
  items - see the Wavetable=419 note in CLAUDE.md).
- There is no way to **load a sample as audio** - existing loaders target instruments and
  effects (`load_instrument_or_effect`, `load_preset`) or full drum kits (`load_drum_kit`).
  There is no audio-clip loader and no single-pad sample loader.
- The User Library lives on **iCloud Drive**, so a sample path may be a dataless
  `.icloud` placeholder. The existing `create_simpler_instrument` reads WAV/AIFF headers
  with stdlib `wave`/`aifc`, which open the file and **would fail on a placeholder** -
  any audio loader must materialize the file first.

The `/ableton:produce` skill (#4b) needs these as reliable single calls to strategically
insert loops/one-shots and populate drum racks.

## Scope

**4 new tools (132 -> 136, new "Samples" category, 20 total):**

1. `search_samples` - LOM browser walk + name-match + classify; READ-only
2. `load_audio_clip` - load a loop into an audio clip slot (**feasibility-gated**)
3. `load_sample_to_drum_pad` - load a one-shot onto a single Drum Rack pad (**feasibility-gated**)
4. `populate_drum_rack` - load many samples to many pads (loops the single-pad loader)

**One new pure module:** `sample_utils.py` (classification, name matching, iCloud
placeholder-path derivation, post-load kind refinement)

**One server.py helper:** `_ensure_local(sample_path, timeout=30)` - iCloud materialization,
called by every loader before any header read.

**No Remote Script changes planned.** All tools orchestrate existing server primitives
(`browser.load_item`, the preset-patch `.adg` infrastructure). The drum-pad spike may
discover a need for a new RS load path - if so, that is decided and scoped at spike time,
not assumed now. Version bump: 0.12.0 -> 0.13.0.

## Approach

Approach A: **one search tool + targeted loaders + a pure util.** Search is a single
server-side browser walk that classifies each hit and ranks by name match. Loaders are
thin: materialize the file, then drive the existing browser/preset-patch load path. All
resolution/normalization happens server-side in `sample_utils.py` (the Remote Script
cannot import it - see CLAUDE.md architecture notes).

## Tool designs

### `search_samples`

```
search_samples(
    query,
    kinds = ["loop", "one_shot", "kit", "instrument"],
    limit = 40,
    sources = ["factory", "user"]
) -> {ok, data}
```

Server-side LOM browser walk over the requested `sources`, name-matching `query`
(space-separated terms, OR) against each item's name and folder, classifying each hit
via `sample_utils.classify_sample`, and returning the ranked top `limit`. READ-only -
it does **not** download anything (a search must not trigger hundreds of iCloud
downloads); it only **flags** `is_icloud_placeholder` so the caller knows a later load
will materialize.

`sources`: `"factory"` walks the Core Library / factory packs; `"user"` walks the User
Library branch (the iCloud-backed one - resolve its path the way the preset-patch tools
do, via the `<UserLibrary>` ProjectPath, not the first `User Library` string).

`kinds`: filter the returned items to these classifications.

Returns:
```json
{
  "count": 312,
  "returned": 40,
  "truncated": true,
  "items": [
    {
      "name": "Kick Deep 01.wav",
      "path": "/Users/.../User Library/Samples/Drums/Kicks/Kick Deep 01.wav",
      "uri": "query:Samples#Kick%20Deep%2001.wav",
      "kind": "one_shot",
      "source": "user",
      "folder": "Samples/Drums/Kicks",
      "is_icloud_placeholder": false
    }
  ]
}
```

`count` is total matches found; `returned`/`truncated` follow the existing reader-limit
convention (CLAUDE.md). `uri` is the browser item URI used by the loaders.

### `load_audio_clip`

```
load_audio_clip(track_index, clip_index, sample_path, track_type="regular") -> {ok, data}
```

Load a sample (typically a loop) into an audio clip slot. **Feasibility-gated** - the
spike confirms whether the LOM can drop a sample onto an audio clip slot before this is
built (see Feasibility gates).

Flow:
1. `_ensure_local(sample_path)` - materialize from iCloud if needed.
2. Resolve the sample's browser item.
3. Select the target audio track + clip slot.
4. `browser.load_item` on the sample's browser item.
5. Confirm an audio clip appeared; return its info.

Errors: undownloaded iCloud placeholder after timeout, track/slot not found, non-audio
track type, sample not a loadable audio format.

### `load_sample_to_drum_pad`

```
load_sample_to_drum_pad(track_index, pad_note, sample_path) -> {ok, data}
```

Load a one-shot onto a single Drum Rack pad (`pad_note` is the MIDI note of the pad).
**Feasibility-gated** - primary path is selecting the pad chain and `browser.load_item`;
fallback is a preset-patch of the Drum Rack `.adg` injecting the sample at the pad's note
(reusing the rack `.adg` backdoor infrastructure). The spike decides which.

Flow:
1. `_ensure_local(sample_path)`.
2. Locate the Drum Rack on the track and the pad chain for `pad_note`.
3. Load the sample onto that pad (primary or fallback path per spike).
4. Return pad assignment confirmation.

Errors: undownloaded placeholder, no Drum Rack on track, invalid pad note.

### `populate_drum_rack`

```
populate_drum_rack(track_index, mapping) -> {ok, data}
```

Load many samples onto many pads in one call. `mapping` is a list of
`{pad_note, sample_path}`. Loops `load_sample_to_drum_pad` per entry; returns per-entry
results (loaded / error) so a partial failure is visible.

Returns:
```json
{
  "track_index": 0,
  "loaded_count": 6,
  "results": [
    {"pad_note": 36, "sample_path": ".../Kick.wav", "status": "loaded"},
    {"pad_note": 38, "sample_path": ".../Snare.wav", "status": "loaded"}
  ]
}
```

## Module: `sample_utils.py`

Pure, no Live dependency, imported by server.py only (offline-testable):

```python
def classify_sample(name: str, path: str) -> str:
    """Return "loop" | "one_shot" | "kit" | "instrument" from name + path."""
    ...

def name_match(query: str, name: str, folder: str) -> tuple:
    """Return (matched: bool, score: int) - term hits + whole-word bonus; ranks results."""
    ...

def icloud_placeholder_path(sample_path: str) -> str | None:
    """Derive the '<dir>/.<name>.icloud' stub path, or None if the real file is present."""
    ...

def refine_kind_by_length(kind, frames, sample_rate, tempo) -> str:
    """Post-load upgrade of a >~2-beat 'one_shot' to 'loop' once length is known."""
    ...
```

**Classification priority** (`classify_sample`):
1. `.adg` under a `Drums`/`Kit` folder -> `kit`
2. instrument preset (`.adv`) -> `instrument`
3. one-shot tokens (`One Shots/`, `Hits/`, `Oneshot`, single-hit names like
   kick/snare/hat/clap/stab) -> `one_shot`
4. loop tokens (`Loops/`, `Loop`, or a BPM in the name -
   `\b\d{2,3}\s?bpm\b` / trailing `_120`) -> `loop`
5. fallback by file extension.

**iCloud placeholder derivation** (`icloud_placeholder_path`): a dataless file is stored
as `<dir>/.<name>.icloud`; once downloaded the real path appears. Returns the stub path
when the real file is absent, else `None`.

## iCloud materialization: `_ensure_local`

Server.py helper, called by **every loader** before any header read:

```
_ensure_local(sample_path, timeout=30) -> resolved local path | error
```

1. `os.path.exists(sample_path)` -> already local, return it.
2. else the `.icloud` stub exists -> `subprocess.run(["/usr/bin/brctl", "download", sample_path])`,
   then poll up to `timeout` seconds for the real path to appear.
3. timeout -> `_err(...)` ("undownloaded iCloud placeholder; download in Finder or retry").

Confirmed: `brctl` is at `/usr/bin/brctl`; the User Library is at
`~/Library/Mobile Documents/com~apple~CloudDocs/Production/User Library` (iCloud). This
must precede any `wave`/`aifc` header read - those open the file and fail on a placeholder.

## Feasibility gates

Per the project standing rule, the **first plan task is a live spike** verifying each
gated loader before it is built. Tool shapes adapt to spike results.

- **`load_audio_clip`:** can the LOM drop a sample onto an audio clip slot? Test: select
  an audio track + slot, `browser.load_item` on the sample's browser item - does an audio
  clip appear? If audio clips turn out to be UI-drag-only, **fallback** = load the loop
  into Simpler in a loop-playback config and report that honestly.
- **`load_sample_to_drum_pad`:** can a sample target a specific Drum Rack pad? Primary:
  the pad is a chain -> select the pad chain, `browser.load_item`. Fallback: preset-patch
  a Drum Rack `.adg` injecting the sample at the pad's note (reuse the rack `.adg` backdoor
  infra). The spike picks the path; only the fallback could require a new RS load path.

## Testing

`sample_utils.py` is fully offline-testable. New test file `tests/test_sample_utils.py`:

- `classify_sample`: ~20 fixtures including real-world names across all four kinds
  (kit `.adg`, instrument `.adv`, one-shot hits, BPM-named loops, extension fallback).
- `name_match`: scoring - term hits, whole-word bonus, ranking order.
- `icloud_placeholder_path`: stub-path derivation; `None` when the real file is present.
- `refine_kind_by_length`: boundary around the ~2-beat threshold.

Tool-level offline tests (monkeypatched, no real Live / no real iCloud):
- `search_samples`: monkeypatched `get_ableton_connection` + a fake browser walk ->
  classified, ranked, limited output with correct count/returned/truncated.
- `_ensure_local`: a temp `.icloud` stub + mocked `subprocess`/poll - already-local
  short-circuit, successful download, and timeout error.

Live-verify the 4 tools after the spikes; record results in PROGRESS.md.

Offline test target: 656 -> ~690 passed.

## Out of scope (#4a)

Honest limits, to be surfaced by the #4b produce skill:

- **Audio preview without loading** - not exposed in the LOM.
- **Content / audio-similarity matching** - search is name/path only, no audio analysis.
- **Auto-warp-to-tempo fine-tuning** - Live auto-warps on load; we don't tweak warp markers
  (warp-marker editing is read-only in the LOM anyway).
- Any Remote Script change beyond what the drum-pad spike may force.

## Version and release

Version 0.12.0 -> 0.13.0. Single PR `feat/sample-sourcing`. RS install only if the
drum-pad spike forces a new load path. Tool count 132 -> 136. New "Samples" category in
`gen_docs_site.py` group map (19 -> 20 categories). Hero counts in `docs/index.md` need
manual update.

Marketplace publish flow is the same as prior releases (bump 3 version files -> `uv lock`
-> commit -> `gh release create v0.13.0` -> bump marketplace ref ->
`node scripts/build-readme.js` -> push marketplace repo).
