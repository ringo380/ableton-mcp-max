# Ruleset Sources

Curated, distilled best-practice guidance. Citations are to authoritative,
publicly available material. Rule `source` fields anchor to the headings below.

## health-naming
Default track names ("1-MIDI", "2-Audio") make sessions hard to navigate.
Renaming every track is standard session-hygiene advice in the Ableton manual's
"Managing Files and Sets" and "Arrangement View" workflow guidance.

## health-cpu-devices
Long device chains on a single track raise CPU load and complicate the signal
path; Ableton's "Computer Audio Resources" guidance recommends freezing/printing
or trimming heavy chains.

## health-leftover-states
Mutes and solos left engaged after editing are a common cause of "missing"
parts on export. Standard mixdown checklist item.

## health-clipping
A channel or the master peaking at or above 0 dBFS clips digitally - the
distortion is baked into the export and cannot be undone in mastering. Detected
by peak-holding Live's post-fader output meters over a short playback pass (or
the audio-tap peak when a tap is connected).

## mixing-gain-staging
Keeping channel faders at or below unity preserves headroom into the master and
matches Ableton's mixer/gain-staging guidance.

## mixing-return-effects
Time-based effects (reverb/delay) are best shared on return tracks rather than
inserted per channel, per Ableton's "Return Tracks and Sends" documentation.

## mastering-headroom
Leave headroom and catch peaks before export. Ableton's "Exporting Audio" and
mastering guidance recommends a limiter on the master and avoiding 0 dBFS overs.

## mastering-export-readiness
Mastering processing belongs on the master bus; a flat master with no dynamics
control is rarely export-ready.

## sound-design-modulation
Static patches benefit from movement (LFO/automation/macros); Ableton's
instrument and "Push/Live sound design" material emphasizes modulation.

## sound-design-reverb-taste
Reverb/delay tails must fit the tempo and arrangement - a judgment call, not a
measurable threshold.

## signal-loudness
Integrated loudness and true-peak targets (EBU R128 / ITU-R BS.1770-4). Streaming
platforms (Spotify, Apple Music, YouTube) normalize around -14 LUFS; a -1 dBTP
ceiling avoids inter-sample clipping on lossy codecs. Measured via the MCP Audio
Tap Max-for-Live device.

## mixing-spectral-masking
Sources sharing the same frequency range mask one another, muddying the mix.
Ableton's mixing guidance and standard practice recommend EQ carving, panning, or
arrangement separation so competing tracks occupy complementary spectral space.
Measured here as pairwise overlap of per-track 8-band energy profiles from the
MCP Tap device.

## mixing-loudness-balance
Relative level balance keeps every part audible. A track sitting far below the
loudest (large integrated-loudness spread) is likely buried. EBU R128 loudness
(BS.1770-4) per track via the MCP Tap device backs this heuristic.

## mixing-per-track-headroom
Per-track gain staging leaves headroom into the master and avoids over-squashing.
A true peak above -1 dBTP risks inter-sample clipping; a low crest factor signals
heavy compression that flattens transients. Mirrors Ableton's gain-staging and
dynamics guidance, measured per track via the MCP Tap device.

## mixing-stereo-correlation
Mono compatibility matters for club, phone, and Bluetooth playback. Strongly
negative inter-channel correlation cancels on mono fold-down. Derived from
mid/side energy (correlation proxy) reported by the MCP Tap device.
