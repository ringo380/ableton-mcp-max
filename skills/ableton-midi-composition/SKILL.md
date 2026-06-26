---
name: ableton-midi-composition
description: Writing and editing MIDI in Ableton Live - chords, basslines, melodies, drum patterns, plus humanize/swing/quantize/scale and groove. Use when composing MIDI, generating chords/bass/melody/drums, quantizing, humanizing, or applying groove.
---

# Ableton MIDI composition

Goal: musical, in-key MIDI parts with human feel.

## Tools
- Generate: `generate_chord_progression`, `generate_bassline`, `generate_melody`,
  `generate_drum_pattern`.
- Edit notes (extended API): `add_notes_to_clip`, `replace_clip_notes`,
  `modify_clip_notes`, `remove_clip_notes`, `get_clip_notes`.
- Feel: `humanize_clip`, `swing_clip`, `quantize_clip`, `quantize_clip_to_scale`,
  `arpeggiate_clip`, `harmonize_clip`. Scale: `set_song_scale`.
- Groove: `get_groove_pool`, `assign_groove_to_clip`, `set_groove_amount`,
  `load_groove_to_pool`, `search_grooves`, `set_swing_amount`.

## Principles
- Set the song key/scale from the brief; `quantize_clip_to_scale` to keep parts in key.
- Compose, then humanize - tiny timing/velocity variance beats dead-grid MIDI.
- Edit notes in place by `note_id` (`modify_clip_notes`), not remove + re-add.

## Gotchas
- NEVER legacy set_notes/remove_notes (blocking modal -> socket timeout). Extended API only.
- Groove vs swing are distinct: `set_swing_amount` only affects FUTURE quantize ops;
  `swing_clip` bakes swing into existing notes; `assign_groove_to_clip` applies a pool
  groove non-destructively (scaled by `set_groove_amount`). A groove must already be in the
  pool to assign it.

## Checklist
- [ ] Parts in the project key/scale.
- [ ] Humanized; not dead-grid.
- [ ] Used the extended note API throughout.
