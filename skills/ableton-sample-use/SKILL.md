---
name: ableton-sample-use
description: Working with audio samples in Ableton Live - finding/loading clips, building drum racks, warping, and stem separation. Use when adding samples, loading audio, building a drum kit, chopping/warping audio, or separating stems.
---

# Ableton sample use

Goal: the right audio in the right place, warped and gain-staged to fit.

## Tools
- Find/load: `search_samples`, `load_audio_clip`.
- Drums: `load_drum_kit`, `populate_drum_rack`, `load_sample_to_drum_pad`.
- Stems: `separate_stems_to_arrangement` (Demucs unmix onto arrangement tracks).
- Pointers: read `samples.md` for the project's sample/stem/reference locations.

## Principles
- Consult `samples.md` first - use the project's curated palette before hunting factory content.
- Warp loops to the set tempo; one-shots usually unwarped.
- Gain-stage loaded audio into the mix like any other track (see ableton-mixing).

## Gotchas
- Sample/drum loads HOT-SWAP onto the target - load onto an empty track for experiments.
- Stem separation lays each stem on its own arrangement track; expect auto-warp quirks -
  verify clip lengths after.
- Loud factory one-shots can clip - check with `check_clipping` after loading.

## Checklist
- [ ] Checked samples.md before sourcing new audio.
- [ ] Loops warped to tempo.
- [ ] No clipping introduced by loaded audio.
