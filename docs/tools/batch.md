---
layout: default
title: Batch & Transactions
parent: Tools
nav_order: 14
---

# Batch & Transactions
{: .no_toc }

Collapse several mutations into a single atomic Live task / socket round-trip.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## batch

```python
batch(commands: List[Dict[str, Any]], stop_on_error: bool = True)
```

Run several state-mutating commands in ONE Live task / one socket round-trip.

Collapses N writes into a single scheduled main-thread task, removing the
per-command settle/latency overhead and making the sequence atomic under
stop_on_error. Use this whenever you would otherwise fire several mutations
back-to-back (e.g. create a track, name it, load an instrument, create a
clip, add notes).

Each member is {"type": <command>, "params": {...}} where <command> is the
WIRE name of a mutating op and params are exactly what that op's remote
handler expects. Examples of <command>: "create_midi_track" (params {index}),
"set_track_name" ({track_index, name}), "create_clip" ({track_index,
clip_index, length}), "add_notes_to_clip" ({track_index, clip_index, notes}),
"set_device_parameter" ({track_index, device_index, parameter_index, value}),
"set_mixer_property" ({track_index, property, value, track_type, send_index}).
Note: to load an instrument/effect by URI use type "load_browser_item" with
params {track_index, item_uri} (the same call load_instrument_or_effect makes).
Members run SYNCHRONOUSLY in the given order.

IMPORTANT constraints:
- Only MUTATIONS are batchable. Read commands (get_*) are rejected; call those
  separately. Name/index resolution that needs a read first (e.g. resolving a
  device parameter by name) must be done before building the batch.
- Do NOT batch operations that depend on a previous write SETTLING
  asynchronously before the next one reads it (e.g. set_song_position then a
  cue toggle). Those must stay separate calls; members here share one Live
  task with no settle between them.

Parameters:
- commands: list of {type, params} mutation members (1..64).
- stop_on_error: if true (default), stop at the first failing member and
  return partial results; if false, attempt every member.

Returns JSON {count, completed, failed_index,
results:[{status, result|message}]} where failed_index is -1 when all ran.

