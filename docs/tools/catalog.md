---
layout: default
title: Catalog
parent: Tools
nav_order: 23
---

# Catalog
{: .no_toc }

Persistent local index of Serum presets, samples, grooves, and device presets, with similarity search and reuse-vs-create recommendation that can orchestrate the existing create tools.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## search_catalog

```python
search_catalog(
    query: str,
    domains: list = None,
    kinds: list = None,
    sources: list = None,
    limit: int = 50,
)
```

Search the local content catalog (Serum presets, samples, grooves, device
presets) by name/folder/tags. Fast persistent index; auto-refreshes changed
filesystem roots. Returns {ok, data:{count, returned, truncated, items}}.

## find_similar

```python
find_similar(intent: str, domain: str, limit: int = 10)
```

Rank catalog assets in one domain by lexical similarity to an intent
string, with scores. domain in serum|sample|groove|device_preset. Returns
{ok, data:{items:[{name, path, uri, source, folder, kind, score}]}}.

## catalog_stats

```python
catalog_stats()
```

Counts and freshness for the local catalog by domain/source/kind, plus
per-root last-indexed times. Returns {ok, data:{total, by_domain, by_source,
by_kind, roots, device_presets_last_indexed}}.

## reindex_catalog

```python
reindex_catalog(domains: list = None, full: bool = False)
```

Rebuild the catalog. domains defaults to all. full=True drops and rebuilds
from scratch. Device presets reindex only when Live is connected. Returns
{ok, data:{indexed:{domain:count}, errors:[...]}}.

## recommend_asset

```python
recommend_asset(intent: str, domain: str)
```

Propose reuse-vs-create for a described asset. domain in
serum|sample|groove|device_preset|wavetable|simpler. Returns {ok, data:
{decision, top_matches, create_plan, reason}}. PROPOSE ONLY - never writes;
pass create_plan to create_from_plan(confirm=True) to act on a 'create'.

## recommend_instrument

```python
recommend_instrument(intent: str, prefer_native: bool = None)
```

Choose which instrument engine to reach for from a free-text intent
(e.g. 'gritty evolving reese bass for dnb'). Ranks Serum vs native Wavetable,
Operator, Analog, Simpler/Sampler, and Drum Rack against a capability matrix,
biased toward native engines so Serum is used only when it earns it. Applies
live signals when connected: Serum-installed (drops Serum if absent), Serum
instance count (busy penalty), and portability (prefer_native). Set
prefer_native=True to force native-only weighting; leave None to auto-detect
(native-preferred only when the set has no 3rd-party plugin). PROPOSE ONLY -
pass the returned top.domain to recommend_asset to pick reuse-vs-create.
Returns {ok, data:{intent, parsed, ranked, top, reason, environment, next}}.

## create_from_plan

```python
create_from_plan(plan: dict, confirm: bool = False)
```

Execute a create_plan from recommend_asset. confirm=False (default)
returns a dry-run describing what would be created and writes nothing.
confirm=True invokes the matching creator (Wavetable, Simpler, or a Serum
base-preset clone). Returns {ok, data:{...}}.

## recommend_track_instrument

```python
recommend_track_instrument(
    track_index: int,
    clip_index: int = 0,
    clip_location: str = 'auto',
    intent: str = '',
    limit: int = 5,
    include_plugins: bool = True,
)
```

Classify a MIDI track's part from its notes and rank presets for it.

Measures the clip (pitch range, polyphony, note length, density), classifies the
musical texture (bass / pad / keys / stabs / lead / arp / drums ...), uses
the track name as a prior (content wins on a conflict, which is reported),
then ranks loadable stock presets from the catalog for that role and lists
installed plugins that suit it. intent adds free text to the ranking
("warm", "boom bap", "orchestral"). clip_location "auto" reads session
slot clip_index and falls back to arrangement clip clip_index. PROPOSE
ONLY - hand chosen {track_index, uri} pairs to apply_instrument_plan.
A plugin candidate loads bare (patch_selection: manual - the LOM cannot
pick a Kontakt library or a VST patch). Returns {ok, data:{track_index,
name, clip, analysis, intent, current_devices, doubles_audio_track,
candidates, plugins, next}}.

## recommend_set_instruments

```python
recommend_set_instruments(
    track_indices: list = None,
    intent: str = '',
    limit: int = 3,
    include_plugins: bool = True,
)
```

recommend_track_instrument for every MIDI track, with set-wide context.

Covers every MIDI track that holds a clip (or the given track_indices), in one call with set-wide context: tempo, a key
guess from all parts together, instruments already in use (a sound used
on another track is ranked down so parts do not collide), and whether a
part doubles an audio track of the same name. Returns {ok, data:{tempo,
key_guess, parts:[...], plan:[{track_index, name, uri, candidate}], skipped,
next}}. plan holds each part's top stock candidate, ready for
apply_instrument_plan after review. PROPOSE ONLY.

## apply_instrument_plan

```python
apply_instrument_plan(assignments: list, confirm: bool = False)
```

Load a reviewed instrument plan (hot-swap) and verify each device.

assignments is a list of {track_index, uri, candidate?} (the plan recommend_set_instruments
returns, edited as needed). confirm=False (default) is a dry run that
writes nothing. confirm=True loads each uri (HOT-SWAP: the track's current
instrument is replaced) and verifies the device landed by re-reading the
track. Returns {ok, data:{applied:[{track_index, name, uri, devices_after,
verified}], failed:[...], dry_run}}; ok is false when any track failed.

