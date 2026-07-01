# Instrument-Selection Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `recommend_instrument` tool (plus a curated capability matrix and skill guidance) that chooses which instrument engine to reach for from a free-text intent, biased toward native engines so Serum is used only when it earns it.

**Architecture:** A new pure module `instrument_select.py` loads a hand-authored capability matrix (`param_maps/instrument_profiles.json`), parses a free-text intent into role/genre/character, and scores each engine. `server.py` resolves three live signals (Serum installed, Serum instance count, portability) and passes them into the pure scorer. The `ableton-sound-design` skill gets a "Choosing the engine" section. Follows the existing catalog/decision-engine pattern exactly.

**Tech Stack:** Python (stdlib `json`, `re`, `os` only), FastMCP tool in `server.py`, pytest. No new third-party dependency.

## Global Constraints

- New code is host-side **pure modules imported by `server.py` only**. The Remote Script (Live's separate Python) never imports them and needs **no new handlers**.
- **No new third-party dependency.** Stdlib + existing modules only.
- All new tools return the house envelope `{ok, data}` / `{ok, error}` via the existing `_ok` / `_err` helpers in `server.py`.
- The tool must **degrade gracefully when Live is disconnected**: fall back to intent-only scoring, set `live_connected: false`, never error on a missing connection.
- The pure scorer takes an **injected `environment` dict** so it is fully unit-testable with no Live connection. All live reads resolve in `server.py` and are passed in.
- ASCII only in all source, docs, commits, and PR text. No AI attribution anywhere (public repo).
- Offline gate: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` + `uv run python -m py_compile` + `uv run python -c "import ableton_mcp_max.server"`. No CI; do not reformat existing files.
- Run every `uv`/`pytest` command with `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"` prefixed (the pyenv `uv` shim is otherwise not found).

---

## File Structure

| File | Responsibility |
|---|---|
| `ableton_mcp_max/param_maps/instrument_profiles.json` (create) | Curated capability matrix: per-engine profiles + role/genre/character tag vocab. Single source of truth. |
| `ableton_mcp_max/instrument_select.py` (create) | Pure logic: `load_profiles`, `parse_intent`, `serum_installed`, `classify_device`, `summarize_environment`, `score`, `recommend`. |
| `tests/test_instrument_select.py` (create) | Unit tests for every function in `instrument_select.py`. |
| `tests/test_recommend_instrument_tool.py` (create) | Server-tool tests (fake connection, monkeypatched detection). |
| `ableton_mcp_max/server.py` (modify) | Import the module; add `_resolve_instrument_env` + the `recommend_instrument` tool. |
| `skills/ableton-sound-design/SKILL.md` (modify) | Add a "Choosing the engine" section. |
| `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock`, `docs/*`, `README.md` (modify) | Ship (Task 7). |

---

## Task 1: Capability matrix + loader

**Files:**
- Create: `ableton_mcp_max/param_maps/instrument_profiles.json`
- Create: `ableton_mcp_max/instrument_select.py`
- Test: `tests/test_instrument_select.py`

**Interfaces:**
- Produces: `load_profiles() -> dict` (loads the JSON next to the module's `param_maps/`). The returned dict has keys `engines` (dict of engine-key -> profile), `role_vocab`, `genre_vocab`, `character_vocab`.
- Produces: the matrix file itself, consumed by all later tasks.

- [ ] **Step 1: Write the matrix data file**

Create `ableton_mcp_max/param_maps/instrument_profiles.json` with EXACTLY this content (note: `serum` includes `"growl"` in its `character` list so a reese/growl intent has an engine to overlap):

```json
{
 "engines": {
  "serum": {
   "display": "Serum 2", "native": false, "creatable": true, "domain": "serum", "cpu": "high",
   "roles": {"bass": 5, "lead": 5, "pad": 4, "pluck": 4, "fx": 5, "drums": 1},
   "genres": ["dnb", "dubstep", "future-bass", "edm", "techno", "trap"],
   "character": ["gritty", "evolving", "modern", "aggressive", "digital", "complex-mod", "growl"],
   "reach_for_when": ["wavetable morphing", "heavy unison", "complex mod matrix", "reese/growl"],
   "avoid_when": ["simple sub", "portability required", "cpu constrained", "acoustic/realistic"]
  },
  "wavetable": {
   "display": "Wavetable (native)", "native": true, "creatable": true, "domain": "wavetable", "cpu": "med",
   "roles": {"bass": 4, "lead": 4, "pad": 5, "pluck": 4, "fx": 4, "drums": 1},
   "genres": ["house", "techno", "edm", "pop", "ambient"],
   "character": ["modern", "clean", "evolving", "digital"],
   "reach_for_when": ["wavetable morph without a 3rd-party plugin", "portable set", "generic pad/lead"],
   "avoid_when": ["extreme growl needing deep mod", "acoustic/realistic"]
  },
  "operator": {
   "display": "Operator (FM)", "native": true, "creatable": false, "domain": "device_preset", "cpu": "low",
   "roles": {"bass": 4, "lead": 4, "pad": 3, "pluck": 5, "fx": 3, "drums": 2},
   "genres": ["house", "techno", "electro", "pop"],
   "character": ["metallic", "clean", "punchy", "digital"],
   "reach_for_when": ["FM bells/plucks", "clean sub", "low cpu", "e-piano/DX-style"],
   "avoid_when": ["wavetable morph", "acoustic/realistic"]
  },
  "analog": {
   "display": "Analog", "native": true, "creatable": false, "domain": "device_preset", "cpu": "low",
   "roles": {"bass": 4, "lead": 4, "pad": 4, "pluck": 3, "fx": 2, "drums": 1},
   "genres": ["house", "techno", "synthwave", "pop", "ambient"],
   "character": ["warm", "vintage", "analog", "smooth"],
   "reach_for_when": ["classic subtractive", "warm analog pad/bass", "low cpu"],
   "avoid_when": ["wavetable morph", "digital/aggressive", "acoustic/realistic"]
  },
  "simpler": {
   "display": "Simpler / Sampler", "native": true, "creatable": true, "domain": "simpler", "cpu": "low",
   "roles": {"bass": 3, "lead": 3, "pad": 3, "pluck": 3, "fx": 4, "drums": 3},
   "genres": ["hip-hop", "lofi", "house", "pop", "ambient"],
   "character": ["acoustic", "realistic", "organic", "vintage", "textural"],
   "reach_for_when": ["acoustic/realistic instrument", "a specific sample as the source", "one-shot/chop"],
   "avoid_when": ["synthesized-from-scratch tone", "deep synthesis mod"]
  },
  "drum_rack": {
   "display": "Drum Rack", "native": true, "creatable": false, "domain": "device_preset", "cpu": "med",
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
  "synthwave": ["synthwave", "retrowave", "80s"],
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
  "digital": ["digital"],
  "textural": ["textural", "granular", "atmospheric", "lush"],
  "punchy": ["punchy", "tight", "snappy"]
 }
}
```

- [ ] **Step 2: Write the failing test for the loader**

Create `tests/test_instrument_select.py`:

```python
from ableton_mcp_max import instrument_select as isel

# valid recommend_asset domains (server.py recommend_asset accepts these)
_VALID_DOMAINS = {"serum", "sample", "groove", "device_preset", "wavetable", "simpler"}
_ROLES = {"bass", "lead", "pad", "pluck", "fx", "drums"}


def test_load_profiles_shape():
    p = isel.load_profiles()
    assert set(["engines", "role_vocab", "genre_vocab", "character_vocab"]).issubset(p)
    assert "serum" in p["engines"] and "wavetable" in p["engines"]


def test_matrix_integrity():
    p = isel.load_profiles()
    for key, eng in p["engines"].items():
        assert eng["domain"] in _VALID_DOMAINS, key
        assert set(eng["roles"]) == _ROLES, key
        assert isinstance(eng["native"], bool) and isinstance(eng["creatable"], bool)
        for c in eng["character"]:
            assert isinstance(c, str)
    # every scored character token category is a real dict entry
    assert "growl" in p["character_vocab"]
    assert "growl" in p["engines"]["serum"]["character"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.instrument_select'`.

- [ ] **Step 4: Write the loader**

Create `ableton_mcp_max/instrument_select.py`:

```python
"""Instrument-selection intelligence: choose which engine to reach for.

Pure module imported by server.py only. Loads a curated capability matrix
(param_maps/instrument_profiles.json), parses a free-text intent, and scores
each engine. Live signals (Serum installed, instance count, portability) are
resolved in server.py and passed in as an environment dict.
"""
import json
import os
import re

_PROFILES_PATH = os.path.join(os.path.dirname(__file__), "param_maps",
                              "instrument_profiles.json")


def load_profiles(path=None):
    """Load the capability matrix. Raises FileNotFoundError if missing."""
    with open(path or _PROFILES_PATH, "r") as fh:
        return json.load(fh)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/param_maps/instrument_profiles.json ableton_mcp_max/instrument_select.py tests/test_instrument_select.py
git commit -m "feat(instrument-select): capability matrix + loader"
```

---

## Task 2: Intent parser

**Files:**
- Modify: `ableton_mcp_max/instrument_select.py`
- Test: `tests/test_instrument_select.py`

**Interfaces:**
- Consumes: `load_profiles() -> dict`.
- Produces: `parse_intent(text, profiles) -> {"role": str|None, "genre": str|None, "character": [str, ...]}`. `role` and `genre` are the first matching vocab category (in the JSON's key order); `character` is all matching categories.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_instrument_select.py`:

```python
def test_parse_intent_reese_bass_dnb():
    p = isel.load_profiles()
    r = isel.parse_intent("gritty evolving reese bass for dnb", p)
    assert r["role"] == "bass"
    assert r["genre"] == "dnb"
    # reese -> growl character; gritty, evolving present
    assert set(["gritty", "evolving", "growl"]).issubset(set(r["character"]))


def test_parse_intent_multiword_genre():
    p = isel.load_profiles()
    r = isel.parse_intent("warm pad for deep house", p)
    assert r["role"] == "pad"
    assert r["genre"] == "house"
    assert "warm" in r["character"]


def test_parse_intent_word_boundary_no_false_match():
    p = isel.load_profiles()
    # "harp" must NOT match the "arp" lead synonym
    r = isel.parse_intent("a harp sound", p)
    assert r["role"] != "lead" or "arp" not in p["role_vocab"]["lead"]  # arp not falsely triggered
    r2 = isel.parse_intent("harp", p)
    assert r2["role"] is None


def test_parse_intent_empty():
    p = isel.load_profiles()
    r = isel.parse_intent("", p)
    assert r == {"role": None, "genre": None, "character": []}
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.instrument_select' has no attribute 'parse_intent'`.

- [ ] **Step 3: Implement the parser**

Append to `ableton_mcp_max/instrument_select.py`:

```python
def _phrase_present(text, phrase):
    """Word-boundary match so 'arp' does not match 'harp'."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def _first_match(text, vocab):
    for category, phrases in vocab.items():
        if any(_phrase_present(text, ph) for ph in phrases):
            return category
    return None


def _all_matches(text, vocab):
    return [category for category, phrases in vocab.items()
            if any(_phrase_present(text, ph) for ph in phrases)]


def parse_intent(text, profiles):
    t = (text or "").lower()
    return {"role": _first_match(t, profiles["role_vocab"]),
            "genre": _first_match(t, profiles["genre_vocab"]),
            "character": _all_matches(t, profiles["character_vocab"])}
```

- [ ] **Step 4: Run to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/instrument_select.py tests/test_instrument_select.py
git commit -m "feat(instrument-select): free-text intent parser"
```

---

## Task 3: Environment helpers (Serum detection, device classifier, summarizer)

**Files:**
- Modify: `ableton_mcp_max/instrument_select.py`
- Test: `tests/test_instrument_select.py`

**Interfaces:**
- Produces: `serum_installed(candidates=None) -> bool` (filesystem check; default candidate list is a module constant).
- Produces: `classify_device(name, class_name) -> "serum" | "plugin" | "native"`.
- Produces: `summarize_environment(tracks_devices, serum_is_installed, prefer_native_arg) -> {"serum_installed": bool, "serum_instances": int, "prefer_native": bool}`. `tracks_devices` is a list of device-lists; each device is a dict with `name` and `class_name`. `prefer_native_arg` is `None` (auto) or an explicit bool. Auto rule: `True` iff the set has at least one device and NO 3rd-party plugin device (instrument or effect).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_instrument_select.py`:

```python
def test_serum_installed_candidates(tmp_path):
    fake = tmp_path / "Serum2.vst3"
    fake.write_text("x")
    assert isel.serum_installed([str(fake)]) is True
    assert isel.serum_installed([str(tmp_path / "nope.vst3")]) is False


def test_classify_device():
    assert isel.classify_device("Serum2", "PluginDevice") == "serum"
    assert isel.classify_device("Serum", "AuPluginDevice") == "serum"
    assert isel.classify_device("Massive X", "PluginDevice") == "plugin"
    assert isel.classify_device("Wavetable", "InstrumentVector") == "native"
    assert isel.classify_device("", "Operator") == "native"


def test_summarize_environment_counts_and_autonative():
    # one native instrument, no 3rd-party -> auto prefer_native True
    devs = [[{"name": "Wavetable", "class_name": "InstrumentVector"}]]
    env = isel.summarize_environment(devs, True, None)
    assert env == {"serum_installed": True, "serum_instances": 0, "prefer_native": True}


def test_summarize_environment_serum_present_blocks_autonative():
    devs = [[{"name": "Serum2", "class_name": "PluginDevice"}],
            [{"name": "Serum2", "class_name": "PluginDevice"}]]
    env = isel.summarize_environment(devs, True, None)
    assert env["serum_instances"] == 2
    assert env["prefer_native"] is False  # a 3rd-party plugin is present


def test_summarize_environment_explicit_prefer_native_overrides():
    devs = [[{"name": "Serum2", "class_name": "PluginDevice"}]]
    env = isel.summarize_environment(devs, True, True)
    assert env["prefer_native"] is True


def test_summarize_environment_empty_set_not_autonative():
    env = isel.summarize_environment([], True, None)
    assert env["prefer_native"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'serum_installed'`.

- [ ] **Step 3: Implement the helpers**

Append to `ableton_mcp_max/instrument_select.py`:

```python
_SERUM_INSTALL_CANDIDATES = [
    "/Library/Audio/Plug-Ins/VST3/Serum2.vst3",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3/Serum2.vst3"),
    "/Library/Audio/Plug-Ins/VST3/Serum.vst3",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3/Serum.vst3"),
    "/Library/Audio/Plug-Ins/Components/Serum2.component",
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components/Serum2.component"),
    "/Library/Audio/Plug-Ins/Components/Serum.component",
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components/Serum.component"),
    "/Library/Audio/Presets/Xfer Records/Serum 2 Presets",
]

_PLUGIN_CLASSES = ("PluginDevice", "AuPluginDevice")


def serum_installed(candidates=None):
    for p in (candidates if candidates is not None else _SERUM_INSTALL_CANDIDATES):
        if os.path.exists(p):
            return True
    return False


def classify_device(name, class_name):
    if class_name in _PLUGIN_CLASSES:
        if name and "serum" in name.lower():
            return "serum"
        return "plugin"
    return "native"


def summarize_environment(tracks_devices, serum_is_installed, prefer_native_arg):
    serum_instances = 0
    third_party = False
    total = 0
    for devs in tracks_devices:
        for d in devs:
            total += 1
            kind = classify_device(d.get("name"), d.get("class_name"))
            if kind == "serum":
                serum_instances += 1
                third_party = True
            elif kind == "plugin":
                third_party = True
    if prefer_native_arg is None:
        prefer_native = bool(total > 0 and not third_party)
    else:
        prefer_native = bool(prefer_native_arg)
    return {"serum_installed": bool(serum_is_installed),
            "serum_instances": serum_instances,
            "prefer_native": prefer_native}
```

- [ ] **Step 4: Run to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/instrument_select.py tests/test_instrument_select.py
git commit -m "feat(instrument-select): serum detection + device/env helpers"
```

---

## Task 4: Scorer + recommend

**Files:**
- Modify: `ableton_mcp_max/instrument_select.py`
- Test: `tests/test_instrument_select.py`

**Interfaces:**
- Consumes: `parse_intent`, `load_profiles`.
- Produces: `score(parsed, profiles, environment) -> [{"engine", "domain", "score", "creatable", "why"}, ...]` sorted by score desc, then engine name asc. `environment` has keys `serum_installed` (bool), `serum_instances` (int), `prefer_native` (bool). Serum is excluded from the list entirely when `serum_installed` is False.
- Produces: `recommend(intent, environment, profiles=None) -> {"intent", "parsed", "ranked", "top": {"engine","domain"}|None, "reason"}`. `top` mirrors `ranked[0]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_instrument_select.py`:

```python
_ENV_OK = {"serum_installed": True, "serum_instances": 0, "prefer_native": False}


def test_score_reese_bass_serum_wins():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty evolving reese bass for dnb", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] == "serum"
    assert ranked[0]["domain"] == "serum"
    assert ranked[0]["creatable"] is True


def test_score_generic_pad_native_wins_over_serum():
    # no genre, generic "pad", no serum-only character -> native bias decides
    p = isel.load_profiles()
    parsed = isel.parse_intent("a pad", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] != "serum"
    assert p["engines"][ranked[0]["engine"]]["native"] is True


def test_score_acoustic_pluck_simpler():
    p = isel.load_profiles()
    parsed = isel.parse_intent("realistic acoustic pluck", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] == "simpler"
    assert ranked[0]["domain"] == "simpler"


def test_score_serum_excluded_when_not_installed():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    env = {"serum_installed": False, "serum_instances": 0, "prefer_native": False}
    ranked = isel.score(parsed, p, env)
    assert all(r["engine"] != "serum" for r in ranked)


def test_score_serum_busy_penalty_demotes():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    top_free = isel.score(parsed, p, _ENV_OK)[0]["engine"]
    busy = {"serum_installed": True, "serum_instances": 5, "prefer_native": False}
    serum_score_busy = [r for r in isel.score(parsed, p, busy) if r["engine"] == "serum"][0]["score"]
    serum_score_free = [r for r in isel.score(parsed, p, _ENV_OK) if r["engine"] == "serum"][0]["score"]
    assert top_free == "serum"
    assert serum_score_busy == serum_score_free - 3.0


def test_score_prefer_native_penalizes_non_native():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    pn = {"serum_installed": True, "serum_instances": 0, "prefer_native": True}
    serum_pn = [r for r in isel.score(parsed, p, pn) if r["engine"] == "serum"][0]["score"]
    serum_free = [r for r in isel.score(parsed, p, _ENV_OK) if r["engine"] == "serum"][0]["score"]
    assert serum_pn == serum_free - 3.0


def test_recommend_shape():
    p = isel.load_profiles()
    out = isel.recommend("gritty reese bass dnb", _ENV_OK, profiles=p)
    assert set(["intent", "parsed", "ranked", "top", "reason"]).issubset(out)
    assert out["top"]["engine"] == out["ranked"][0]["engine"]
    assert out["top"]["domain"] == out["ranked"][0]["domain"]


def test_recommend_operator_routes_to_device_preset():
    p = isel.load_profiles()
    # FM bell pluck favors operator; operator is non-creatable -> device_preset
    out = isel.recommend("metallic fm bell pluck", _ENV_OK, profiles=p)
    op = [r for r in out["ranked"] if r["engine"] == "operator"][0]
    assert op["domain"] == "device_preset"
    assert op["creatable"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'score'`.

- [ ] **Step 3: Implement the scorer**

Append to `ableton_mcp_max/instrument_select.py`:

```python
ROLE_WEIGHT = 1.0
GENRE_WEIGHT = 2.0
# CHAR_WEIGHT tuned to 2.5 (the spec's "tunable default") so a decisive
# character signal like "acoustic" pushes Simpler above Operator's strong
# FM-pluck role. A single character match outweighs a genre match by design.
CHAR_WEIGHT = 2.5
NATIVE_BONUS = 1.0
SERUM_BUSY_THRESHOLD = 3
SERUM_BUSY_PENALTY = 3.0
NON_NATIVE_PENALTY = 3.0


def _base_score(eng, parsed):
    s = 0.0
    if parsed["role"]:
        s += ROLE_WEIGHT * float(eng["roles"].get(parsed["role"], 0))
    if parsed["genre"] and parsed["genre"] in eng.get("genres", []):
        s += GENRE_WEIGHT
    overlap = sum(1 for c in parsed["character"] if c in eng.get("character", []))
    s += CHAR_WEIGHT * overlap
    if eng.get("native"):
        s += NATIVE_BONUS
    return s


def _why(eng, parsed, penalties):
    parts = []
    if parsed["role"]:
        parts.append("role %s fit %d" % (parsed["role"], eng["roles"].get(parsed["role"], 0)))
    if parsed["genre"] and parsed["genre"] in eng.get("genres", []):
        parts.append("genre %s" % parsed["genre"])
    ov = [c for c in parsed["character"] if c in eng.get("character", [])]
    if ov:
        parts.append("character " + "/".join(ov))
    if eng.get("native"):
        parts.append("native bias")
    parts.extend(penalties)
    return "; ".join(parts) or "no strong signal"


def score(parsed, profiles, environment):
    out = []
    for key, eng in profiles["engines"].items():
        if key == "serum" and not environment.get("serum_installed", True):
            continue
        s = _base_score(eng, parsed)
        penalties = []
        if key == "serum" and environment.get("serum_instances", 0) >= SERUM_BUSY_THRESHOLD:
            s -= SERUM_BUSY_PENALTY
            penalties.append("serum-busy penalty")
        if environment.get("prefer_native") and not eng.get("native"):
            s -= NON_NATIVE_PENALTY
            penalties.append("non-native penalty")
        out.append({"engine": key, "domain": eng["domain"],
                    "score": round(s, 3), "creatable": bool(eng.get("creatable")),
                    "why": _why(eng, parsed, penalties)})
    out.sort(key=lambda r: (-r["score"], r["engine"]))
    return out


def recommend(intent, environment, profiles=None):
    profiles = profiles or load_profiles()
    parsed = parse_intent(intent, profiles)
    ranked = score(parsed, profiles, environment)
    top = ({"engine": ranked[0]["engine"], "domain": ranked[0]["domain"]}
           if ranked else None)
    if top:
        reason = "%s leads (%s)." % (ranked[0]["engine"], ranked[0]["why"])
    else:
        reason = "No engine available (Serum not installed and no fallback matched)."
    return {"intent": intent, "parsed": parsed, "ranked": ranked,
            "top": top, "reason": reason}
```

- [ ] **Step 4: Run to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_instrument_select.py -q`
Expected: PASS (20 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/instrument_select.py tests/test_instrument_select.py
git commit -m "feat(instrument-select): engine scorer + recommend"
```

---

## Task 5: Server tool `recommend_instrument`

**Files:**
- Modify: `ableton_mcp_max/server.py` (add import near line 154; add `_resolve_instrument_env` + the tool near the other catalog tools, after `create_from_plan` at line 8365, before `# Main execution`)
- Test: `tests/test_recommend_instrument_tool.py`

**Interfaces:**
- Consumes: `instrument_select.recommend`, `instrument_select.serum_installed`, `instrument_select.summarize_environment`; existing `get_ableton_connection`, `_ok`, `_err`, `logger`.
- Produces: `_resolve_instrument_env(prefer_native) -> dict` (adds `live_connected`); the `recommend_instrument` MCP tool returning `{ok, data:{intent, parsed, ranked, top, reason, environment, next}}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recommend_instrument_tool.py`:

```python
import json
import ableton_mcp_max.server as server
import ableton_mcp_max.instrument_select as isel


class _Conn:
    """Fake connection: get_session_info + per-track get_track_info."""
    def __init__(self, tracks):
        self._tracks = tracks  # list of device-lists

    def send_command(self, command_type, params=None, **kw):
        if command_type == "get_session_info":
            return {"track_count": len(self._tracks)}
        if command_type == "get_track_info":
            i = params["track_index"]
            return {"index": i, "devices": self._tracks[i]}
        raise AssertionError("unexpected command %s" % command_type)


def test_recommend_instrument_connected_reese(monkeypatch):
    conn = _Conn([[{"name": "Wavetable", "class_name": "InstrumentVector"}]])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: True)
    out = json.loads(server.recommend_instrument(ctx=None,
                                                 intent="gritty reese bass dnb"))
    assert out["ok"] is True
    d = out["data"]
    assert d["top"]["engine"] == "serum"
    assert d["environment"]["live_connected"] is True
    assert d["environment"]["serum_instances"] == 0
    assert "recommend_asset" in d["next"]


def test_recommend_instrument_serum_absent(monkeypatch):
    conn = _Conn([[]])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: False)
    out = json.loads(server.recommend_instrument(ctx=None,
                                                 intent="gritty reese bass dnb"))
    assert out["ok"] is True
    assert all(r["engine"] != "serum" for r in out["data"]["ranked"])
    assert out["data"]["environment"]["serum_installed"] is False


def test_recommend_instrument_disconnected(monkeypatch):
    def _boom():
        raise RuntimeError("Could not connect to Ableton")
    monkeypatch.setattr(server, "get_ableton_connection", _boom)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: True)
    out = json.loads(server.recommend_instrument(ctx=None, intent="a pad"))
    assert out["ok"] is True
    assert out["data"]["environment"]["live_connected"] is False
    assert out["data"]["top"] is not None  # still ranks intent-only
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_recommend_instrument_tool.py -q`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'recommend_instrument'`.

- [ ] **Step 3: Add the import**

In `ableton_mcp_max/server.py`, after line 154 (`from ableton_mcp_max import catalog_adapt`), add:

```python
from ableton_mcp_max import instrument_select
```

- [ ] **Step 4: Add the resolver + tool**

In `ableton_mcp_max/server.py`, immediately after `create_from_plan` ends (line 8365, the blank line before `# Main execution`), insert:

```python
def _resolve_instrument_env(prefer_native):
    """Resolve the live signals recommend_instrument scores against. Degrades to
    filesystem-only + intent-only scoring when Live is disconnected."""
    installed = instrument_select.serum_installed()
    try:
        conn = get_ableton_connection()
        info = conn.send_command("get_session_info")
        n = int(info.get("track_count", 0))
        tracks_devices = []
        for i in range(n):
            ti = conn.send_command("get_track_info", {"track_index": i})
            tracks_devices.append(ti.get("devices", []))
        env = instrument_select.summarize_environment(tracks_devices, installed,
                                                      prefer_native)
        env["live_connected"] = True
        return env
    except Exception as e:
        logger.warning("recommend_instrument env fallback: %s", e)
        return {"serum_installed": installed, "serum_instances": 0,
                "prefer_native": bool(prefer_native) if prefer_native is not None
                else False, "live_connected": False}


@mcp.tool()
def recommend_instrument(ctx: Context, intent: str,
                         prefer_native: bool = None) -> str:
    """Choose which instrument engine to reach for from a free-text intent
    (e.g. 'gritty evolving reese bass for dnb'). Ranks Serum vs native Wavetable,
    Operator, Analog, Simpler/Sampler, and Drum Rack against a capability matrix,
    biased toward native engines so Serum is used only when it earns it. Applies
    live signals when connected: Serum-installed (drops Serum if absent), Serum
    instance count (busy penalty), and portability (prefer_native). Set
    prefer_native=True to force native-only weighting; leave None to auto-detect
    (native-preferred only when the set has no 3rd-party plugin). PROPOSE ONLY -
    pass the returned top.domain to recommend_asset to pick reuse-vs-create.
    Returns {ok, data:{intent, parsed, ranked, top, reason, environment, next}}."""
    try:
        env = _resolve_instrument_env(prefer_native)
        result = instrument_select.recommend(intent, env)
        result["environment"] = env
        top = result.get("top")
        result["next"] = (("Pass domain=%r to recommend_asset to pick "
                           "reuse-vs-create." % top["domain"]) if top
                          else "No engine matched.")
        return _ok(result)
    except FileNotFoundError as e:
        return _err("instrument profiles missing: %s" % e)
    except Exception as e:
        logger.error("recommend_instrument error: %s", e)
        return _err("recommend_instrument error: %s" % e)
```

- [ ] **Step 5: Run the tool tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_recommend_instrument_tool.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Verify the server imports cleanly**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_recommend_instrument_tool.py
git commit -m "feat(instrument-select): recommend_instrument MCP tool"
```

---

## Task 6: Skill guidance

**Files:**
- Modify: `skills/ableton-sound-design/SKILL.md`

**Interfaces:** none (documentation). Verification is by reading + a grep assertion.

- [ ] **Step 1: Add the "Choosing the engine" section**

In `skills/ableton-sound-design/SKILL.md`, insert this section immediately after the `## Tools` section and before `## Principles`:

```markdown
## Choosing the engine
- Before loading a synth for a described sound, call `recommend_instrument` with
  a free-text intent (role + genre + character, e.g. "gritty evolving reese bass
  for dnb"). It ranks the engines and returns a `top.domain` to feed
  `recommend_asset`.
- Default to native (Wavetable / Operator / Analog) for subs, generic pads, and
  FM keys - lighter, recall-safe, no 3rd-party dependency. Wavetable (native)
  covers most wavetable needs.
- Escalate to Serum only for wavetable morphing, heavy unison, complex mod, or
  reese/growl - or when the user names Serum.
- Prefer Simpler/Sampler for acoustic/realistic tones or when a specific sample
  is the source; Drum Rack for percussion.
- Flow: `recommend_instrument` (pick engine) -> `recommend_asset(domain)`
  (reuse-vs-create) -> `create_from_plan` or load a preset.
```

- [ ] **Step 2: Verify the section landed**

Run: `grep -c "recommend_instrument" skills/ableton-sound-design/SKILL.md`
Expected: `2` (or higher).

- [ ] **Step 3: Commit**

```bash
git add skills/ableton-sound-design/SKILL.md
git commit -m "docs(sound-design): choosing-the-engine guidance"
```

---

## Task 7: Ship (version bump, docs, release chain)

**Files:**
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock`, `docs/tools/*`, `docs/tools/index.md`, `commands/tool-index.md`, `docs/index.md`, `README.md`

**Interfaces:** none. This is the release mechanics per CLAUDE.md.

- [ ] **Step 1: Confirm the full offline gate is green**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile ableton_mcp_max/instrument_select.py ableton_mcp_max/server.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all pass; full suite green (prior 1009 + the new instrument-select tests).

- [ ] **Step 2: Bump the version to 0.28.0**

Edit `pyproject.toml` (`version = "0.28.0"`) and `.claude-plugin/plugin.json` (`"version": "0.28.0"`), then sync the lock:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 3: Regenerate the tool index/docs**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: tool count rises 171 -> 172.

- [ ] **Step 4: Hand-bump the hardcoded counts**

The regen scripts do NOT touch these. Update every hardcoded `171` tool-count occurrence to `172`:
- `docs/index.md` (5 spots: description, tagline, two `stats__num`, and the "exposes the N `@mcp.tool()`" line).
- `README.md` (the "reference for all N tools" line near line 7).

Verify none remain:
```bash
grep -rn "171 tools\|all 171\|171 @mcp" docs/index.md README.md || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Commit the ship**

```bash
git add pyproject.toml .claude-plugin/plugin.json uv.lock docs README.md commands/tool-index.md
git commit -m "chore: instrument-selection intelligence (recommend_instrument, v0.28.0, 172 tools)"
```

- [ ] **Step 6: Update PROGRESS.md + memory (post-merge)**

After the PR merges and the release chain is verified, record the ship in `PROGRESS.md` and the memory files per CLAUDE.md. Release chain (per CLAUDE.md): branch -> PR -> `gh pr merge --squash --delete-branch` -> `gh release create v0.28.0` -> bump the `ableton` `ref` to `v0.28.0` in the marketplace repo's `.claude-plugin/marketplace.json` -> `node scripts/build-readme.js` -> push. Verify: local `main` = `origin/main` = `git ls-remote --tags origin v0.28.0` commit = marketplace `ref`. Confirm `gh api user --jq .login` is `ringo380` before any GitHub write.

---

## Live Verification (manual, post-merge; record in PROGRESS.md)

Not part of the offline gate; run against the open Live set after shipping:

1. `recommend_instrument("gritty evolving reese bass for dnb")` -> `top.engine == "serum"`, `environment.serum_installed == true`, `environment.serum_instances` reflects the real set.
2. `recommend_instrument("warm analog pad")` -> a native engine tops (wavetable/analog), not Serum.
3. `recommend_instrument("realistic acoustic guitar pluck")` -> `top.engine == "simpler"`.
4. Load a Serum instance on a track, re-run #1 -> `serum_instances` increments; load three -> Serum takes the busy penalty and a native engine may top.
5. Round-trip: take #1's `top.domain` ("serum") into `recommend_asset(intent, "serum")` and confirm it returns a reuse-or-create decision.
