---
description: Autonomously produce a full track in Ableton Live - brief, foundation, parts, arrangement, mix, master - pausing at each stage to audition and redirect.
allowed-tools: ["Bash", "Read", "AskUserQuestion"]
---

# /ableton:produce

Build a complete track from an empty (or near-empty) Live set: brief -> foundation -> parts -> arrangement -> mix -> master. Each stage runs automatically, then PAUSES so you can hear it and redirect before the next stage. This is not a blind one-shot to a finished master, and not a confirm-every-write crawl - the stage boundary is the redirect unit.

> If MCP tools aren't loaded yet, fetch the core set: `ToolSearch select:mcp__AbletonMCPMax__get_session_info,mcp__AbletonMCPMax__set_tempo,mcp__AbletonMCPMax__create_midi_track,mcp__AbletonMCPMax__load_instrument_or_effect,mcp__AbletonMCPMax__generate_chord_progression,mcp__AbletonMCPMax__build_arrangement,mcp__AbletonMCPMax__balance_mix,mcp__AbletonMCPMax__analyze_set` (load others per stage as needed).

**Argument:** free text brief, e.g. `/ableton:produce lofi hip hop, 84 bpm, dreamy, 2 minutes`. Anything omitted is filled from the genre table below.

## Honest limits (state these to the user up front)

- Sample selection is by name/path keyword, not by listening - no audio-content matching.
- Real mix/master levels need MCP Tap devices loaded; without taps the mix/master pass is configuration-only and is marked un-metered (never invent dB/LUFS).
- Per-track taps are PRE-FADER (the tap is a device, the fader is after the chain): per-track LUFS reflects instrument level, not the fader, so you cannot verify a fader balance by re-measuring the same taps, and master/program loudness needs a tap on the MASTER (the only post-fader point) - which `deploy_taps` does not auto-add. State master loudness as un-measured unless a master tap is present.
- No arrangement TIMELINE automation (MCP can't write param envelopes bound to timeline position). "FX automation" = self-animating LFO devices (Auto Filter / Auto Pan) + static return sends, which are constant across the whole arrangement. Clip envelopes don't survive `build_arrangement`.
- Generated parts are musically-sensible but algorithmic starting points - the checkpoint loop is how you shape them.
- Scope is one track/idea: empty set -> one arranged structure. Not multi-song, not stem export.

## Checkpoint protocol (every stage except Brief)

1. Do the stage's work autonomously. On a HARD failure (a tool returns `{"ok": false}` that blocks the stage), STOP and report the `error` - do not start the next stage on a broken foundation.
2. Print a short summary of what changed (tracks / clips / sections / levels touched).
3. AUTO-FIRE playback so the result is already audible: `fire_scene` the loop (Foundation/Parts), `set_song_position(0)` + `start_playback` (Arrangement), or play the densest section (Mix/Master).
4. Pause and offer `continue / adjust / redo`:
   - `continue` -> `stop_playback`, advance.
   - `adjust` -> take the note, rework WITHIN this stage, re-checkpoint.
   - `redo` -> clear this stage's outputs and redo it, re-checkpoint.

Verify writes before advancing: Live applies many writes asynchronously, so re-read state a stage depends on (`get_transport` for tempo, `get_session_info` for tracks, `get_arrangement_clips` for the timeline) rather than trusting a tool's own success string. See `/ableton:best-practices` (write-lag, connection triage, undo scope).

## Genre defaults

Fill any brief gap from this table; for a genre not listed, derive sensible values from these anchors using your judgment. Structure templates are section maps for `build_arrangement` (scale lengths to the requested total).

| Genre | Tempo | Structure template (bars) | Density / energy | Master LUFS target |
|-------|-------|---------------------------|------------------|--------------------|
| House | 122-126 | Intro 16 / Build 16 / Drop 32 / Break 16 / Drop 32 / Outro 16 | driving, 4-on-floor | -8 |
| Techno | 128-134 | Intro 16 / Build 16 / Main 32 / Break 16 / Main 32 / Outro 16 | hypnotic, sparse-to-dense | -7 |
| Hip-hop / lo-fi | 80-92 | Intro 4 / Verse 16 / Hook 8 / Verse 16 / Hook 8 / Outro 4 | laid-back, swung | -10 |
| Drum & bass | 170-176 | Intro 16 / Build 8 / Drop 32 / Break 16 / Drop 32 / Outro 16 | fast, breakbeat | -7 |
| Ambient | 60-90 | Intro 16 / Evolve 32 / Peak 16 / Resolve 16 | slow, evolving pads | -14 |
| Pop | 100-120 | Intro 4 / Verse 16 / Chorus 8 / Verse 16 / Chorus 8 / Bridge 8 / Chorus 8 / Outro 4 | vocal-forward | -9 |
| Trap | 130-150 (half-time feel) | Intro 8 / Verse 16 / Hook 8 / Verse 16 / Hook 8 / Outro 8 | 808-heavy, hi-hat rolls | -8 |

## Stage 1 - Brief

1. Re-read the set: `get_session_info` (never assume a track layout - see `/ableton:best-practices`).
2. Parse the argument for genre/style, mood/reference words, key, tempo, length/structure, sample keywords.
3. Fill gaps from the genre table: unknown tempo -> genre default; unknown structure -> genre template scaled to the requested length; mood words -> nudge density/energy and the LUFS target; unknown key -> read the set scale (composition tools expose the song scale) else a genre-sensible default.
4. Ask ONE consolidated `AskUserQuestion` ONLY for choices that genuinely change output and can't be safely defaulted (typically: genre if truly unstated, and total length). Do not interrogate field-by-field.
5. Print the resolved plan (genre, key, tempo, structure, sample plan, mix/master targets) and confirm before building. No playback in this stage.

## Stage 2 - Foundation

- `set_tempo`; verify with a separate `get_transport` (write-lag).
- Create the tracks the template calls for and load instruments - see `/ableton:new-track` for creation + the HOT-SWAP warning (loading replaces an existing instrument; build on empty tracks).
- Source keyword-driven samples: `search_samples` -> `load_drum_kit` / `populate_drum_rack` (drums) / `load_audio_clip` (loops). iCloud materialization and feasibility gates live inside those tools. NOTE: drum "kits" are browser DEVICES (`.adg` under `Drums/`), not samples - load via the device browser, not `search_samples` (which walks sample trees only). For a MONOPHONIC lead, avoid sampled "chord"/"stab" presets (e.g. "* Stab", "* Chord", "Chord Pluck"): they trigger a whole chord sample per note, so single-note lines stack transposed chords and clash. Use a bare single-oscillator synth (Wavetable, Operator) for leads.
- Checkpoint: there are no notes yet, so DON'T auto-fire (an empty loop is silent) - print a summary of the tracks + instruments loaded and pause for redirect.

## Stage 3 - Parts

- Generate clips per track, keyed to the brief's key/scale: `generate_chord_progression`, `generate_bassline`, `generate_melody`, `generate_drum_pattern`. These use the safe extended-note API (never legacy set_notes - see `/ableton:best-practices`).
- Ensure a scene exists for the loop row (`create_scene` if needed).
- Generated parts are rhythmically straight. For a swung/shuffled feel, either `swing_clip` to bake swing into a clip's notes (e.g. `amount="66%"`, `grid="1/16"`), or `assign_groove_to_clip` to bind a Groove-Pool groove (list it with `get_groove_pool`; the pool must already contain a groove - see `/ableton:best-practices`). `humanize_clip` adds subtle timing/velocity variation.
- Checkpoint: `fire_scene` on the full loop.

## Stage 4 - Arrangement

- Build the section map from the genre structure template scaled to the brief's length (name + length_bars + clips per section).
- `build_arrangement(..., write_locators=True)` to place Session clips on the timeline; locators let it round-trip through `get_arrangement_structure` (Live auto-names locators sequentially, not by section - expected).
- Verify with `get_arrangement_clips` before advancing.
- Checkpoint: `back_to_arrangement` then `set_song_position(0)` + `start_playback`. Tell the user to press **Tab** to view the Arrangement - `build_arrangement` writes the timeline but the Session loop stays in place, so a user looking at Session sees no change.

### Optional - FX & movement (between Arrangement and Mix)

Offer to add FX/movement if the brief calls for vibe/atmosphere. Timeline automation is not writable (see Honest limits), so use:
- Self-animating devices: `load_instrument_or_effect` an Auto Filter with a tempo-synced LFO (low-pass, `LFO T Mode`=Synced, set `LFO 16th` to a 2-4 bar cycle, `LFO Amount` ~0.5) on a pad/chord track for an evolving sweep; Auto Pan for stereo movement.
- Return sends: `set_mixer_property(property="send")` toward the default A-Reverb / B-Delay returns for depth.
These are constant across the arrangement (no per-section automation). Checkpoint: play a section where the affected tracks sound together.

## Stage 5 - Mix

- TAP GATE: check `list_taps` / `get_audio_tap_status`. If no taps are connected, OFFER to `deploy_taps`: if the user accepts, continue with real signal work; if they decline, proceed configuration-only and clearly mark the mix as un-metered (never fabricate levels). Re-check `list_taps` after deploy: a slow Live-12 boot can FALSE-NEGATIVE a per-track load (reports failed though the tap connected) - trust the registry, retry only the truly-missing tracks.
- `balance_mix` / `gain_stage_track` / `adjust_track_gain` toward the brief's targets. See `/ableton:analyze` for the metering rationale and the "Needs metering" framing.
- Measure on the SESSION full-loop scene (`fire_scene`) where all parts sound at once - no single arrangement section contains every track, so a section window mis-measures balance. Per-track taps are PRE-FADER (see Honest limits): the measured LUFS is the instrument level and won't change when you move a fader, so use the measurement to set faders but don't expect a re-measure to confirm them; treat the `balance` finding as "this instrument is quiet," not "this fader is low."
- Checkpoint: play the densest section (`set_song_position` to that section's start + `start_playback`).

## Stage 6 - Master

- `analyze_set(focus="mastering", measure=<True if taps present>)`, then `apply_findings` for the deterministic master-bus corrections against the genre LUFS target. Report judgment-required findings; do not auto-apply them. NOTE: `apply_findings` has NO deterministic action for `mastering.limiter_present` - adding the limiter is judgment-required. The standard finishing move is a Limiter as the last master device (ceiling ~-1 dB, Mode=True Peak); add it explicitly via `load_instrument_or_effect(track_type="master")` + `set_device_parameter`.
- Program loudness vs the LUFS target and `mastering.true_peak` are DEFERRED unless a MASTER tap is connected (per-track taps don't cover the master bus). Without one, state loudness as un-measured - do not fabricate it.
- Checkpoint: final playback from the top + a closing summary (tracks, structure, measured vs target loudness, what was and wasn't auto-applied).

## Failure and cleanup

- Stop-and-report on the first blocking `{"ok": false}` within a stage; surface the `error`, don't advance.
- First-call-after-restart "Could not connect" is usually the reconnect race - retry once, then triage per `/ableton:best-practices`.
- The goal is a kept track, so partial outputs are left in place on failure for the user to keep or discard - the command does not auto-delete in-progress work.
