# Instrument-Selection Intelligence - Design

**Date:** 2026-06-30
**Status:** Approved (design); ready for implementation plan
**Repo:** ableton-mcp-max

## Goal

Give the MCP server the "DAW intelligence" to choose which instrument *engine*
to reach for when designing a sound - Serum vs native Wavetable vs Operator vs
Analog vs Simpler/Sampler vs Drum Rack - grounded in a curated capability
matrix and live environment signals, with a default bias toward native engines
so Serum is used only when it earns it.

## Problem

The existing decision engine `recommend_asset(intent, domain)` requires the
caller to *already know the domain* (serum / wavetable / simpler / sample /
groove / device_preset). It only decides reuse-vs-create *within* a family that
has already been chosen. Nothing helps pick the family in the first place, and
the `ableton-sound-design` skill mentions Serum nowhere and gives no
engine-selection guidance - it jumps straight to load/probe/backdoor. Because
this repo has invested heavily in Serum tooling, the model has a structural pull
to over-reach for Serum. This feature adds the missing selection layer and
counter-weights that bias.

## Scope

In scope:

1. **Capability matrix** - a hand-authored static data file describing each
   instrument engine's strengths, character, role fit, CPU cost, and explicit
   reach-for / avoid triggers.
2. **`recommend_instrument` tool** - parses a free-text intent, scores each
   engine against the matrix, applies live environment modifiers, and returns a
   ranked recommendation that chains into the existing `recommend_asset`.
3. **Skill guidance** - extend `ableton-sound-design` with a "Choosing the
   engine" section that encodes the prefer-native-unless default in prose.

Explicitly OUT of scope:

- **Other 3rd-party instrument VSTs** beyond Serum. They have no authored
  capability profile and no creation tooling; the model can only "load" them, so
  ranking them adds no value here.
- **Semantic / embedding intent parsing.** v1 parsing is lexical keyword
  matching against the matrix's tag vocabulary (same style as
  `recommend_asset`'s free-text intent). The LLM supplies good intent strings.
- **A real CPU meter.** Live's LOM exposes no CPU load; "CPU budget" is
  approximated by counting existing Serum instances only.
- **New creators.** Operator/Analog/Drum Rack have no create tool; the tool
  routes them to `device_preset` (reuse an existing preset). This feature adds no
  authoring tools.

## Global Constraints

- New code is host-side **pure modules imported by `server.py` only**. The Remote
  Script (Live's separate Python) never imports them and needs no new handlers.
- **No new third-party dependency.** Stdlib + existing modules only.
- All new tools return the house envelope `{ok, data}` / `{ok, error}` via the
  existing `_ok` / `_err` helpers.
- The tool must **degrade gracefully when Live is disconnected**: fall back to
  intent-only scoring, set `live_connected: false`, never error on a missing
  connection.
- The pure scorer takes an **injected `environment` dict** so it is fully
  unit-testable with no Live connection. All live reads resolve in `server.py`
  and are passed in.
- ASCII only in all source, docs, commits, and PR text. No AI attribution
  anywhere (public repo).
- Offline gate: `uv run --with pytest pytest -q` + `py_compile` +
  `uv run python -c "import ableton_mcp_max.server"`. No CI; do not reformat
  existing files.

## Architecture

```
server.py
   |  recommend_instrument tool:
   |    1. resolve environment signals (Serum installed, instance count, portability)
   |    2. call instrument_select.recommend(intent, environment, prefer_native)
   |    3. return {ok, data}
   |  imports
   v
instrument_select.py   (pure: load matrix, parse intent, score, rank)
   |  loads
   v
param_maps/instrument_profiles.json   (curated capability matrix; single source of truth)
```

No module reaches back into `server.py`. The three live signals are resolved on
the server (they need the Ableton connection and filesystem) and passed into the
pure scorer as a plain dict.

### Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `param_maps/instrument_profiles.json` | Curated capability matrix: per-engine profiles + role/genre/character tag vocab. | (data) |
| `instrument_select.py` | `load_profiles()`, `parse_intent(text, profiles)`, `score(parsed, profiles, environment)`, `recommend(intent, environment, prefer_native)`. Pure given its inputs. | stdlib `json`, `re` |
| `server.py` (tool + env resolvers) | `recommend_instrument` tool; resolve Serum-installed, Serum-instance-count, portability; assemble `environment`; envelope the result. | `instrument_select`; existing connection + browser helpers |

## Capability Matrix (`instrument_profiles.json`)

```json
{
  "engines": {
    "serum": {
      "display": "Serum 2",
      "native": false,
      "creatable": true,
      "domain": "serum",
      "cpu": "high",
      "roles": {"bass": 5, "lead": 5, "pad": 4, "pluck": 4, "fx": 5, "drums": 1},
      "genres": ["dnb", "dubstep", "future-bass", "edm", "techno", "trap"],
      "character": ["gritty", "evolving", "modern", "aggressive", "digital", "complex-mod"],
      "reach_for_when": ["wavetable morphing", "heavy unison", "complex mod matrix", "reese/growl"],
      "avoid_when": ["simple sub", "portability required", "cpu constrained", "acoustic/realistic"]
    },
    "wavetable": {
      "display": "Wavetable (native)",
      "native": true, "creatable": true, "domain": "wavetable", "cpu": "med",
      "roles": {"bass": 4, "lead": 4, "pad": 5, "pluck": 4, "fx": 4, "drums": 1},
      "genres": ["house", "techno", "edm", "pop", "ambient"],
      "character": ["modern", "clean", "evolving", "digital"],
      "reach_for_when": ["wavetable morph without a 3rd-party plugin", "portable set", "generic pad/lead"],
      "avoid_when": ["extreme growl needing deep mod", "acoustic/realistic"]
    },
    "operator": {
      "display": "Operator (FM)",
      "native": true, "creatable": false, "domain": "device_preset", "cpu": "low",
      "roles": {"bass": 4, "lead": 4, "pad": 3, "pluck": 5, "fx": 3, "drums": 2},
      "genres": ["house", "techno", "electro", "pop"],
      "character": ["metallic", "clean", "punchy", "digital"],
      "reach_for_when": ["FM bells/plucks", "clean sub", "low cpu", "e-piano/DX-style"],
      "avoid_when": ["wavetable morph", "acoustic/realistic"]
    },
    "analog": {
      "display": "Analog",
      "native": true, "creatable": false, "domain": "device_preset", "cpu": "low",
      "roles": {"bass": 4, "lead": 4, "pad": 4, "pluck": 3, "fx": 2, "drums": 1},
      "genres": ["house", "techno", "synthwave", "pop", "ambient"],
      "character": ["warm", "vintage", "analog", "smooth"],
      "reach_for_when": ["classic subtractive", "warm analog pad/bass", "low cpu"],
      "avoid_when": ["wavetable morph", "digital/aggressive", "acoustic/realistic"]
    },
    "simpler": {
      "display": "Simpler / Sampler",
      "native": true, "creatable": true, "domain": "simpler", "cpu": "low",
      "roles": {"bass": 3, "lead": 3, "pad": 3, "pluck": 3, "fx": 4, "drums": 3},
      "genres": ["hip-hop", "lofi", "house", "pop", "ambient"],
      "character": ["acoustic", "realistic", "organic", "vintage", "textural"],
      "reach_for_when": ["acoustic/realistic instrument", "a specific sample as the source", "one-shot/chop"],
      "avoid_when": ["synthesized-from-scratch tone", "deep synthesis mod"]
    },
    "drum_rack": {
      "display": "Drum Rack",
      "native": true, "creatable": false, "domain": "device_preset", "cpu": "med",
      "roles": {"bass": 1, "lead": 1, "pad": 1, "pluck": 1, "fx": 2, "drums": 5},
      "genres": ["hip-hop", "house", "techno", "dnb", "trap", "pop"],
      "character": ["percussive", "organic", "punchy"],
      "reach_for_when": ["drums/percussion", "beat/kit", "layered one-shots"],
      "avoid_when": ["melodic/tonal instrument"]
    }
  },
  "role_vocab": {
    "bass": ["bass", "sub", "reese", "808", "bassline"],
    "lead": ["lead", "melody", "topline", "arp", "hook"],
    "pad": ["pad", "atmosphere", "ambient", "drone", "wash", "strings"],
    "pluck": ["pluck", "stab", "key", "keys", "bell", "mallet", "e-piano", "rhodes"],
    "fx": ["fx", "riser", "sweep", "impact", "texture", "noise", "downlifter"],
    "drums": ["drum", "drums", "kick", "snare", "hat", "hihat", "perc", "percussion", "beat", "kit"]
  },
  "genre_vocab": {
    "dnb": ["dnb", "drum and bass", "drum-and-bass", "neurofunk"],
    "dubstep": ["dubstep", "riddim", "brostep"],
    "future-bass": ["future bass", "future-bass"],
    "house": ["house", "deep house", "tech house"],
    "techno": ["techno"],
    "trap": ["trap"],
    "hip-hop": ["hip hop", "hip-hop", "boom bap", "boom-bap", "lofi", "lo-fi"],
    "edm": ["edm", "big room", "festival"],
    "synthwave": ["synthwave", "retrowave", "80s", "vintage synth"],
    "ambient": ["ambient", "cinematic", "soundtrack"],
    "pop": ["pop"],
    "electro": ["electro"]
  },
  "character_vocab": {
    "gritty": ["gritty", "dirty", "grungy", "distorted"],
    "evolving": ["evolving", "moving", "morphing", "animated", "modulated"],
    "aggressive": ["aggressive", "hard", "harsh", "screaming"],
    "growl": ["growl", "reese", "neuro"],
    "warm": ["warm", "smooth", "round"],
    "vintage": ["vintage", "analog", "retro", "classic", "old-school"],
    "clean": ["clean", "pure", "hi-fi", "crisp"],
    "metallic": ["metallic", "fm", "bell", "glassy"],
    "acoustic": ["acoustic", "realistic", "real", "natural", "organic", "live"],
    "digital": ["digital", "modern"],
    "textural": ["textural", "granular", "atmospheric", "lush"],
    "punchy": ["punchy", "tight", "snappy"]
  }
}
```

Notes:
- `reach_for_when` / `avoid_when` are prose triggers primarily for the skill and
  the `why` string; scoring uses `roles` / `genres` / `character`.
- `growl` in `character_vocab` maps to Serum's `character` only (it is not a
  Serum tag literally spelled "growl"; the scorer treats the extracted character
  token and matches it against each engine's `character` list, and Serum's
  `reach_for_when` names reese/growl - so growl-tokened intents favor Serum via
  the character overlap on "gritty"/"aggressive" plus the reese role synonym).
  Concretely: "reese" is both a `bass` role synonym and a `growl` character
  synonym, and only Serum lists reese/growl affinity, so it wins cleanly.

## Intent Parsing

`parse_intent(text, profiles)`:

1. Lowercase, tokenize on non-alphanumerics (keep multi-word phrases by also
   scanning the raw lowercased string for each vocab phrase).
2. **role:** the first `role_vocab` category with a phrase present in the text
   (single role; if none, role is `null` and role fit contributes 0).
3. **genre:** first `genre_vocab` category with a phrase present (single genre;
   may be `null`).
4. **character:** all `character_vocab` categories with a phrase present (list;
   may be empty).

Returns `{"role": str|None, "genre": str|None, "character": [str, ...]}`.

## Scoring

`score(parsed, profiles, environment)` returns a list of
`{engine, domain, score, creatable, why}` sorted by `score` descending.

Per engine:

```
base = ROLE_WEIGHT   * (roles[parsed.role] if parsed.role else 0)      # roles 0-5, ROLE_WEIGHT = 1.0
     + GENRE_WEIGHT   * (1 if parsed.genre in engine.genres else 0)     # GENRE_WEIGHT = 2.0
     + CHAR_WEIGHT    * (count of parsed.character in engine.character) # CHAR_WEIGHT = 1.5

native_bias = NATIVE_BONUS if engine.native else 0                      # NATIVE_BONUS = 1.0

score = base + native_bias + env_modifiers(engine, environment)
```

`env_modifiers`:
- If `engine == serum` and `environment.serum_installed is False`:
  **exclude the engine entirely** (do not return it; add a note in the reason).
- If `engine == serum` and `environment.serum_instances >= SERUM_BUSY_THRESHOLD`
  (default 3): `score -= SERUM_BUSY_PENALTY` (default 3.0).
- If `environment.prefer_native is True` and not `engine.native`:
  `score -= NON_NATIVE_PENALTY` (default 3.0).

Constants live at module top for tuning. The native bias is deliberately small
so a clear Serum-shaped request (reese/growl, wavetable morph) still wins, while
ties and generic requests fall to the portable native engine.

`why` is a short generated string naming the top contributing factors (role fit,
genre match, character overlap, and any penalty applied).

## Tool Contract

`recommend_instrument(intent: str, prefer_native: bool | None = None)`:

**Server-side environment resolution (before calling the pure scorer):**
- `serum_installed`: check known install locations for Serum 2 - the VST3
  (`/Library/Audio/Plug-Ins/VST3/Serum2.vst3` and user Library equivalent), the
  AU component, OR the factory content dir already referenced by the catalog
  (`/Library/Audio/Presets/Xfer Records/Serum 2 Presets`). Presence of any =
  installed. Pure filesystem; works even if Live is disconnected.
- `serum_instances`: if Live connected, walk tracks + devices and count devices
  whose class/name identifies Serum. If disconnected, `0` and
  `live_connected: false`.
- `prefer_native`: if the caller passes an explicit bool, use it. If `None` and
  Live is connected, auto-detect: `True` when the set contains at least one
  instrument and zero non-native (3rd-party) instruments; else `False`. If
  disconnected and `None`, default `False`.

**Return (inside `{ok:true, data:{...}}`):**

```json
{
  "intent": "gritty evolving reese bass for dnb",
  "parsed": {"role": "bass", "genre": "dnb", "character": ["gritty", "evolving", "growl"]},
  "ranked": [
    {"engine": "serum", "domain": "serum", "score": 8.5, "creatable": true, "why": "..."},
    {"engine": "wavetable", "domain": "wavetable", "score": 6.0, "creatable": true, "why": "..."}
  ],
  "top": {"engine": "serum", "domain": "serum"},
  "environment": {"serum_installed": true, "serum_instances": 1, "prefer_native": false, "live_connected": true},
  "next": "Pass domain='serum' to recommend_asset to pick reuse-vs-create.",
  "reason": "Serum leads on evolving/gritty reese despite the native bias."
}
```

**Engine -> `recommend_asset` domain mapping:** carried on each engine as
`domain`. `serum -> serum`, `wavetable -> wavetable`, `simpler -> simpler` (the
three creatable domains, full reuse-vs-create). `operator`, `analog`,
`drum_rack -> device_preset` (no create tool; reuse an existing preset), and
those are marked `creatable: false` so the model loads a preset rather than
calling `create_from_plan`.

**Full flow:** `recommend_instrument` (pick engine) ->
`recommend_asset(domain)` (reuse-vs-create within it) -> `create_from_plan` or
load a preset. The existing chain is unchanged; this sits in front of it.

## Skill Integration

Add a "Choosing the engine" section to `ableton-sound-design` (no new skill -
keeps the skill-description budget flat):

- Call `recommend_instrument` before loading a synth for a described sound.
- Default to native (Wavetable / Operator / Analog) for subs, generic pads, and
  FM keys - lighter, recall-safe, no 3rd-party dependency.
- Escalate to Serum only for wavetable morphing, heavy unison, complex mod, or
  reese/growl - or when the user names Serum.
- Route the returned `domain` into `recommend_asset`.

The prose mirrors the matrix so the model's default reasoning is already right
even before it calls the tool.

## Error Handling

- **Live disconnected:** resolve `serum_installed` from the filesystem,
  `serum_instances = 0`, `prefer_native` per the rule above, set
  `live_connected: false`, and score intent-only. Never error.
- **Malformed / empty intent:** parse yields all-null; scoring returns engines
  ranked by native bias + genre/character only (role fit 0). Still a valid,
  useful ranking (favors native). No error.
- **Missing/corrupt matrix file:** the tool returns `{ok:false, error}` with a
  clear message (this is a shipped data file, so absence is a real bug, not a
  runtime condition to paper over).
- All exceptions in server-side env resolution are caught and downgraded to the
  disconnected path (missing signal, not tool failure).

## Testing

Offline gate: `uv run --with pytest pytest -q` + `py_compile` + server import.

- **`instrument_select.parse_intent`:** role/genre/character extraction incl.
  multi-word phrases; null role/genre; multiple character tags; the
  reese-favors-Serum case.
- **`instrument_select.score`:** base scoring math; native-bias tie-break
  (generic "pad" with no genre -> a native engine tops Serum); Serum excluded
  when `serum_installed False`; Serum penalty at/above the busy threshold;
  non-native penalty under `prefer_native`; ranking order.
- **`recommend` shape:** `top` matches `ranked[0]`; `domain` per engine correct;
  `creatable` flags correct.
- **Matrix integrity:** every engine has a `domain` that is a valid
  `recommend_asset` domain; every `roles` table covers the six roles; vocab
  categories referenced by scoring exist.
- **Live verification (manual, post-merge, recorded in PROGRESS.md):**
  `serum_installed` detection on the real machine; `serum_instances` off a real
  set with a Serum instance loaded; a few end-to-end
  intent -> `recommend_instrument` -> `recommend_asset` round-trips (a reese ->
  serum, a generic pad -> native, an acoustic pluck -> simpler).

## Ship Convention (per CLAUDE.md)

- +1 tool (171 -> 172). Joins the existing catalog/decision category (no new
  category).
- Version bump in `pyproject.toml` + `.claude-plugin/plugin.json` + `uv.lock`
  (next minor **v0.28.0**).
- Regenerate docs via `build_tool_index.py` / `gen_docs_site.py`; hand-bump the
  hardcoded counts in `docs/index.md` (5 spots) and `README.md`.
- Branch -> PR -> squash-merge -> tag -> bump marketplace `ref` +
  `build-readme.js` -> push marketplace repo.
- Verify the release chain: local main = origin/main = `git ls-remote` tag commit
  = marketplace `ref`.
