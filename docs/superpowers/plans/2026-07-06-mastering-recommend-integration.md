# Mastering Recommend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recommend-then-apply mastering intelligence: a free-text intent + loudness target produces a proposed Ozone 12 chain, applies it in one shot, then the mastering skill converges on the target via a live measure/nudge loop.

**Architecture:** Two pure modules (`master_profiles.py`, `master_select.py`) hold the curated character->chain profiles and intent parsing, imported by `server.py` only (mirrors `instrument_select.py`). Two new deterministic MCP tools (`recommend_master` PROPOSE-ONLY, `apply_master` one-shot setup) surface them. The judgment loop lives in the rewritten `ableton-mastering` skill and the `/ableton:produce` Master stage.

**Tech Stack:** Python 3.13 (uv env), FastMCP, existing Ozone state-blob tooling (`ozone_state_utils`, `ozone_utils`, `set_ozone_state`), existing catalog (`catalog_query`, `catalog_decide`), pytest.

## Global Constraints

- **PROPOSE ONLY:** `recommend_master` never writes to Live or disk.
- **Chain shape:** `recommend_master`'s `chain` is a `{module_alias: {param_name: value}}` dict in the EXACT shape `set_ozone_state`'s `changes` arg accepts (module aliases per `ozone_utils.ALIAS_TO_BLOB`, e.g. `"MAX"`, `"EQ"`, `"DYN"`).
- **Ozone-12-only:** `apply_master` detects Ozone via the existing `_osu.is_ozone_state` guard (through `set_ozone_state`) and errors clearly when absent. No native-Ableton fallback in this phase.
- **Live path in the loop:** the skill's convergence loop uses `set_ozone_maximizer` (Configure path, no reload). `set_ozone_state` (reloads the set) is used ONCE at apply, never inside the loop.
- **No new dependencies.** Pure stdlib + existing modules.
- **Style:** match surrounding code - `%`-formatting (not f-strings) in modules that mirror `instrument_select.py`; every MCP tool returns `_ok(...)`/`_err(...)` JSON and callers check `ok`.
- **Offline gate:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` and `uv run python -c "import ableton_mcp_max.server"` must pass.
- **No AI attribution** in any commit message (public repo). Standard hyphen `-` only.

---

## File Structure

- `ableton_mcp_max/master_profiles.py` (create) - the five character buckets, the semantic-slot -> real-blob-key map (`PARAM_KEYS`), and `build_chain(bucket, target, true_peak)` emitting a `set_ozone_state`-shaped dict.
- `ableton_mcp_max/master_select.py` (create) - intent parsing (bucket + platform), target resolution, and `recommend(intent, target, true_peak)` assembling the proposal. Consumes `master_profiles`.
- `ableton_mcp_max/server.py` (modify) - two new `@mcp.tool()`s (`recommend_master`, `apply_master`) + module imports.
- `tests/test_master_profiles.py`, `tests/test_master_select.py`, `tests/test_recommend_master_tool.py`, `tests/test_apply_master_tool.py` (create).
- `skills/ableton-mastering/SKILL.md` (rewrite).
- `commands/produce.md` (modify - Master stage).
- Docs: `docs/index.md`, `README.md`, `commands/tool-index.md`, `docs/tools/*` (count bump + regen).

---

## Task 0: Ozone param-key spike (CONTROLLER pre-step, LIVE, main loop - NOT a subagent)

This is a controller step, run in the main loop against a live Ableton with Ozone 12 on the master. It captures the exact state-blob param key strings and native ranges that `master_profiles.PARAM_KEYS` needs. Do this BEFORE dispatching Task 1 and paste the captured keys into Task 1's brief.

- [ ] **Step 1:** Ensure Live is open with Ozone 12 on the master. Call `get_ozone_state(track_index=0, track_type="master")` for the per-module summary, then `get_ozone_state(0, "master", module="MAX")`, `... module="EQ"`, `... module="DYN"`.
- [ ] **Step 2:** Record, into `.superpowers/sdd/ozone-keys.md`, the exact `name` strings + observed `value`/type for: Maximizer bypass, target loudness, ceiling, character; EQ bypass (+ one low-shelf and one high-shelf band's gain/freq/type key names if present); Dynamics bypass (+ threshold/ratio key names if present). Confirmed from Phase 2: Maximizer `Target Loudness [dB]`, Dynamics `Sidechain HPF`, and module bypass keys appear as `Bypass` or `Global Bypass`.
- [ ] **Step 3:** In Task 1's dispatch brief, fill `PARAM_KEYS` values verbatim from these captured strings. Any slot whose real key you could NOT confirm stays `None` (build_chain drops `None`-keyed slots; the live gate surfaces it via `skipped`).

> If Live is unavailable at planning time, dispatch Task 1 with only the two confirmed keys filled (`max_target`, and module `Bypass`) and the rest `None`; the tonal slots are additive and can be filled in a later top-up. The plan is fully testable and shippable with just those.

---

## Task 1: master_profiles.py (curated buckets + build_chain)

**Files:**
- Create: `ableton_mcp_max/master_profiles.py`
- Test: `tests/test_master_profiles.py`

**Interfaces:**
- Consumes: `ableton_mcp_max.ozone_utils.ALIAS_TO_BLOB` (to validate emitted aliases).
- Produces:
  - `BUCKETS: tuple[str]` = `("transparent", "warm", "loud_club", "punchy", "bright")`
  - `PARAM_KEYS: dict[str, tuple[str, str]]` - semantic slot -> `(module_alias, blob_param_name)` (real keys from the Task 0 spike).
  - `build_chain(bucket: str, target_lufs: float, true_peak: float) -> dict` - `{module_alias: {param_name: value}}`, ready for `set_ozone_state`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_master_profiles.py
import pytest
import ableton_mcp_max.master_profiles as mp
from ableton_mcp_max.ozone_utils import ALIAS_TO_BLOB


def test_buckets_are_five():
    assert mp.BUCKETS == ("transparent", "warm", "loud_club", "punchy", "bright")


def test_build_chain_passes_target_through_to_maximizer():
    chain = mp.build_chain("transparent", -14.0, -1.0)
    alias, pname = mp.PARAM_KEYS["max_target"]
    assert chain[alias][pname] == -14.0


def test_build_chain_always_sets_ceiling_and_isc():
    chain = mp.build_chain("transparent", -14.0, -1.0)
    a, ck = mp.PARAM_KEYS["max_ceiling"]
    _, ik = mp.PARAM_KEYS["max_isc"]
    assert chain["MAX"][ck] == -1.0        # Margin = ceiling
    assert chain["MAX"][ik] is True        # Prevent Intersample Clipping


def test_build_chain_enables_maximizer():
    chain = mp.build_chain("transparent", -12.0, -1.0)
    _, bk = mp.PARAM_KEYS["max_bypass"]
    assert chain["MAX"][bk] is False       # bypass False == module on


def test_build_chain_louder_target_is_higher_value():
    quiet = mp.build_chain("transparent", -14.0, -1.0)
    loud = mp.build_chain("loud_club", -8.0, -1.0)
    a, p = mp.PARAM_KEYS["max_target"]
    assert loud[a][p] > quiet[a][p]  # -8 > -14


def test_build_chain_only_emits_known_aliases():
    for b in mp.BUCKETS:
        chain = mp.build_chain(b, -12.0, -1.0)
        for alias in chain:
            assert alias in ALIAS_TO_BLOB, "unknown module alias %s" % alias


def test_warm_bucket_lifts_low_and_enables_band():
    chain = mp.build_chain("warm", -14.0, -1.0)
    _, le = mp.PARAM_KEYS["eq_low_enable"]
    _, lg = mp.PARAM_KEYS["eq_low_gain"]
    # A nonzero shelf gain must be accompanied by enabling that band.
    assert chain["EQ"][lg] > 0
    assert chain["EQ"][le] is True


def test_transparent_bucket_has_no_eq_shaping():
    # Flat EQ (0/0) -> no EQ block emitted (nothing to enable).
    chain = mp.build_chain("transparent", -14.0, -1.0)
    assert "EQ" not in chain


def test_buckets_have_distinct_eq_fingerprints():
    shapes = {b: (mp.BUCKET_SHAPES[b]["eq_low_gain"],
                  mp.BUCKET_SHAPES[b]["eq_high_gain"]) for b in mp.BUCKETS}
    assert len(set(shapes.values())) == len(mp.BUCKETS)  # all five differ


def test_unknown_bucket_raises():
    with pytest.raises(KeyError):
        mp.build_chain("nonsense", -12.0, -1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_master_profiles.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the implementation**

Real blob keys are from the Task 0 spike. IMPORTANT CAVEAT (Phase 2 limit): the
state blob does NOT encode chain membership - all ~40 Ozone modules are always
present. Only the Maximizer is guaranteed to be in the default Ozone chain, so it
reliably affects sound. EQ shelves are BEST-EFFORT: audible only if the user has
the Equalizer in their active Ozone chain, harmless otherwise. That is why the
Maximizer settings are unconditional and the EQ block is emitted only when a
bucket asks for a nonzero shelf (and always paired with enabling that band).

```python
# ableton_mcp_max/master_profiles.py
"""Curated Ozone-12 mastering profiles: character bucket -> chain.

Pure module imported by server.py only. Each bucket maps to concrete Ozone
state-blob params, emitted as a {module_alias: {param_name: value}} dict in the
exact shape set_ozone_state accepts. PARAM_KEYS holds the real blob key strings
captured from a get_ozone_state spike (plan Task 0).

Reliability note: the state blob does not encode chain membership, so only the
Maximizer (always in the default Ozone chain) reliably affects sound. The EQ
shelves are best-effort - they shape tone only if the Equalizer is in the user's
active chain, and are harmless otherwise.
"""

BUCKETS = ("transparent", "warm", "loud_club", "punchy", "bright")

# Semantic slot -> (module alias, real blob param name). From the Task 0 spike.
PARAM_KEYS = {
    "max_bypass":     ("MAX", "Bypass"),                        # False = module on
    "max_target":     ("MAX", "Target Loudness [dB]"),
    "max_ceiling":    ("MAX", "Margin"),                        # dB; 0 default, negative = headroom
    "max_isc":        ("MAX", "Prevent Intersample Clipping"),  # True = true-peak safe
    "eq_bypass":      ("EQ", "Bypass"),                         # False = module on
    "eq_low_enable":  ("EQ", "Band 1 Enable"),                 # ~100 Hz low shelf
    "eq_low_gain":    ("EQ", "Band 1 Gain"),
    "eq_high_enable": ("EQ", "Band 8 Enable"),                 # ~16 kHz high shelf
    "eq_high_gain":   ("EQ", "Band 8 Gain"),
}

# Per-bucket EQ shelf gains (dB). Each bucket has a distinct fingerprint. Tonal
# EQ is best-effort (see module docstring); the Maximizer loudness/ceiling is the
# reliable part of every chain.
BUCKET_SHAPES = {
    "transparent": {"eq_low_gain": 0.0,  "eq_high_gain": 0.0},
    "warm":        {"eq_low_gain": 1.0,  "eq_high_gain": -0.5},
    "loud_club":   {"eq_low_gain": 0.5,  "eq_high_gain": 0.5},
    "punchy":      {"eq_low_gain": -0.5, "eq_high_gain": 0.5},
    "bright":      {"eq_low_gain": -0.5, "eq_high_gain": 1.5},
}


def _put(chain, slot, value):
    """Place value at PARAM_KEYS[slot] into the chain (value None -> skip)."""
    if value is None:
        return
    alias, pname = PARAM_KEYS[slot]
    chain.setdefault(alias, {})[pname] = value


def build_chain(bucket, target_lufs, true_peak):
    """Build a set_ozone_state-shaped changes dict for a character bucket.

    Maximizer settings (enable, target, ceiling, true-peak safety) are always
    emitted - they are the reliable part of the chain. target_lufs passes through
    to the Maximizer target (louder = higher, e.g. -8 > -14); true_peak sets the
    Margin (ceiling). EQ shelves are emitted only for a nonzero bucket gain, each
    paired with enabling its band. Raises KeyError for an unknown bucket.
    """
    shape = BUCKET_SHAPES[bucket]  # KeyError on unknown bucket (tested)
    chain = {}
    # Maximizer - unconditional (always in the default Ozone chain).
    _put(chain, "max_bypass", False)
    _put(chain, "max_target", float(target_lufs))
    _put(chain, "max_ceiling", float(true_peak))
    _put(chain, "max_isc", True)
    # EQ shelves - best-effort, only when the bucket asks for a nonzero gain.
    low = float(shape["eq_low_gain"])
    high = float(shape["eq_high_gain"])
    if low != 0.0:
        _put(chain, "eq_bypass", False)
        _put(chain, "eq_low_enable", True)
        _put(chain, "eq_low_gain", low)
    if high != 0.0:
        _put(chain, "eq_bypass", False)
        _put(chain, "eq_high_enable", True)
        _put(chain, "eq_high_gain", high)
    return chain
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_master_profiles.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/master_profiles.py tests/test_master_profiles.py
git commit -m "feat: master_profiles character buckets + build_chain"
```

---

## Task 2: master_select.py (intent parse + target resolution + recommend)

**Files:**
- Create: `ableton_mcp_max/master_select.py`
- Test: `tests/test_master_select.py`

**Interfaces:**
- Consumes: `ableton_mcp_max.master_profiles` (`BUCKETS`, `build_chain`).
- Produces:
  - `REUSE_MIN_SCORE = 2`
  - `parse_intent(text: str) -> dict` = `{"bucket", "platform", "keywords"}`
  - `resolve_target(parsed: dict, target_arg: float | None) -> tuple[float, str]` = `(lufs, source)`
  - `recommend(intent: str, target: float = None, true_peak: float = -1.0) -> dict` = `{"intent","parsed","target","true_peak","chain","decision","reason"}` (decision always `"create"`; the catalog layer in server.py may upgrade it to `"reuse"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_master_select.py
import ableton_mcp_max.master_select as ms


def test_parse_bucket_loud_club():
    p = ms.parse_intent("loud club master for a festival")
    assert p["bucket"] == "loud_club"


def test_parse_bucket_defaults_transparent():
    assert ms.parse_intent("just finish it")["bucket"] == "transparent"


def test_platform_target_spotify():
    p = ms.parse_intent("warm master for spotify")
    lufs, src = ms.resolve_target(p, None)
    assert lufs == -14.0 and src.startswith("platform")


def test_platform_target_apple():
    p = ms.parse_intent("clean apple music master")
    assert ms.resolve_target(p, None)[0] == -16.0


def test_explicit_target_overrides_platform():
    p = ms.parse_intent("club master for spotify")  # club + spotify both present
    lufs, src = ms.resolve_target(p, -9.0)
    assert lufs == -9.0 and src == "explicit"


def test_default_target_when_no_signal():
    p = ms.parse_intent("master this")
    assert ms.resolve_target(p, None) == (-14.0, "default")


def test_recommend_shape():
    out = ms.recommend("warm vinyl-style master", target=None)
    assert out["decision"] == "create"
    assert out["parsed"]["bucket"] == "warm"
    assert out["target"] == -14.0
    assert out["true_peak"] == -1.0
    assert isinstance(out["chain"], dict) and "MAX" in out["chain"]


def test_recommend_explicit_target_flows_into_chain():
    out = ms.recommend("loud club", target=-8.0)
    assert out["target"] == -8.0
    from ableton_mcp_max.master_profiles import PARAM_KEYS
    a, p = PARAM_KEYS["max_target"]
    assert out["chain"][a][p] == -8.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_master_select.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/master_select.py
"""Mastering-selection intelligence: intent -> character bucket + target -> chain.

Pure module imported by server.py only. Parses a free-text intent into a
character bucket and optional platform, resolves the loudness target, and builds
the proposed Ozone chain via master_profiles. PROPOSE ONLY - never writes. The
catalog reuse-vs-create layer lives in server.py (it needs the catalog conn).
"""
import re

from ableton_mcp_max import master_profiles

REUSE_MIN_SCORE = 2
DEFAULT_TARGET = -14.0
DEFAULT_TRUE_PEAK = -1.0

# Character bucket -> keyword phrases (word-boundary matched).
BUCKET_VOCAB = {
    "loud_club":   ["loud", "club", "festival", "banging", "edm", "slammed"],
    "warm":        ["warm", "vintage", "analog", "analogue", "smooth", "vinyl"],
    "bright":      ["bright", "airy", "crisp", "presence", "sparkle", "sheen"],
    "punchy":      ["punchy", "punch", "transient", "snappy", "aggressive"],
    "transparent": ["transparent", "clean", "natural", "gentle", "subtle"],
}
DEFAULT_BUCKET = "transparent"

# Platform keyword -> integrated LUFS target.
PLATFORM_TARGETS = {
    "spotify": -14.0, "amazon": -14.0, "youtube": -14.0,
    "apple music": -16.0, "apple": -16.0,
    "club": -8.0, "dj": -8.0,
}


def _phrase_present(text, phrase):
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def parse_intent(text):
    t = (text or "").lower()
    # Bucket: highest keyword count wins; ties -> BUCKET_VOCAB insertion order.
    keywords = []
    best_bucket, best_n = DEFAULT_BUCKET, 0
    for bucket, phrases in BUCKET_VOCAB.items():
        hits = [ph for ph in phrases if _phrase_present(t, ph)]
        keywords.extend(hits)
        if len(hits) > best_n:
            best_bucket, best_n = bucket, len(hits)
    # Platform: first match ("apple music" before "apple").
    platform = None
    for name in sorted(PLATFORM_TARGETS, key=len, reverse=True):
        if _phrase_present(t, name):
            platform = name
            break
    return {"bucket": best_bucket, "platform": platform, "keywords": keywords}


def resolve_target(parsed, target_arg):
    if target_arg is not None:
        return float(target_arg), "explicit"
    if parsed.get("platform"):
        return PLATFORM_TARGETS[parsed["platform"]], "platform:%s" % parsed["platform"]
    return DEFAULT_TARGET, "default"


def recommend(intent, target=None, true_peak=DEFAULT_TRUE_PEAK):
    parsed = parse_intent(intent)
    lufs, src = resolve_target(parsed, target)
    tp = DEFAULT_TRUE_PEAK if true_peak is None else float(true_peak)
    chain = master_profiles.build_chain(parsed["bucket"], lufs, tp)
    reason = "%s bucket, target %.1f LUFS (%s), ceiling %.1f dBTP." % (
        parsed["bucket"], lufs, src, tp)
    return {"intent": intent, "parsed": parsed, "target": lufs,
            "true_peak": tp, "chain": chain, "decision": "create",
            "reason": reason}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_master_select.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/master_select.py tests/test_master_select.py
git commit -m "feat: master_select intent parse + target resolution"
```

---

## Task 3: recommend_master MCP tool + catalog layer

**Files:**
- Modify: `ableton_mcp_max/server.py` (add imports near line 156-158; add tool near the other recommend tools ~line 8805)
- Test: `tests/test_recommend_master_tool.py`

**Interfaces:**
- Consumes: `master_select.recommend`, `master_select.REUSE_MIN_SCORE`, existing `_catalog_conn`, `_ensure_device_index`, `catalog_query.find_similar(conn, intent, "device_preset", limit=5)`, `_ok`/`_err`.
- Produces: `recommend_master(ctx, intent, target=None, true_peak=-1.0, prefer_reuse=True) -> str`.

- [ ] **Step 1: Write the failing test** (mirrors `tests/test_recommend_instrument_tool.py` harness)

```python
# tests/test_recommend_master_tool.py
import json
import ableton_mcp_max.server as server


def test_recommend_master_create_no_catalog(monkeypatch):
    # Catalog unavailable -> profile chain still returned, top_matches empty.
    def _boom():
        raise RuntimeError("catalog offline")
    monkeypatch.setattr(server, "_catalog_conn", _boom)
    out = json.loads(server.recommend_master(ctx=None,
                                             intent="warm master for spotify"))
    assert out["ok"] is True
    d = out["data"]
    assert d["decision"] == "create"
    assert d["parsed"]["bucket"] == "warm"
    assert d["target"] == -14.0
    assert "MAX" in d["chain"]
    assert d["top_matches"] == []
    assert "apply_master" in d["next"]


def test_recommend_master_explicit_target(monkeypatch):
    monkeypatch.setattr(server, "_catalog_conn",
                        lambda: (_ for _ in ()).throw(RuntimeError("off")))
    out = json.loads(server.recommend_master(ctx=None, intent="loud club",
                                             target=-8.0))
    assert out["ok"] is True
    assert out["data"]["target"] == -8.0


def test_recommend_master_reuse_when_catalog_matches(monkeypatch):
    class _Conn:
        pass
    monkeypatch.setattr(server, "_catalog_conn", lambda: _Conn())
    monkeypatch.setattr(server, "_ensure_device_index", lambda conn: None)
    monkeypatch.setattr(server.catalog_query, "find_similar",
                        lambda conn, intent, domain, limit=5: [
                            {"name": "Ozone Master Loud", "path": "/x/ozone.adv",
                             "score": 3}])
    out = json.loads(server.recommend_master(ctx=None, intent="loud club master"))
    assert out["ok"] is True
    assert out["data"]["decision"] == "reuse"
    assert out["data"]["top_matches"][0]["score"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_recommend_master_tool.py -q`
Expected: FAIL (`recommend_master` not defined).

- [ ] **Step 3: Add imports**

Near `ableton_mcp_max/server.py` lines 156-158 (after the `ozone_*` imports), add:

```python
from ableton_mcp_max import master_select as _msel
from ableton_mcp_max import catalog_query
```

(If `catalog_query` is already imported elsewhere in server.py, do NOT duplicate it - reuse the existing import; the test references `server.catalog_query`, so ensure the name `catalog_query` is bound at module scope.)

- [ ] **Step 4: Add the tool** (place just before `recommend_instrument`, ~line 8805)

```python
def _is_master_preset(row):
    """Best-effort filter: catalog rows that look like a master/Ozone preset."""
    hay = ("%s %s" % (row.get("name", ""), row.get("path", ""))).lower()
    return "ozone" in hay or "master" in hay


@mcp.tool()
def recommend_master(ctx: Context, intent: str, target: float = None,
                     true_peak: float = -1.0, prefer_reuse: bool = True) -> str:
    """Propose an Ozone 12 mastering chain from a free-text intent + loudness
    target. Picks a character bucket (transparent/warm/loud_club/punchy/bright)
    and resolves the LUFS target (explicit arg > platform keyword like
    spotify/apple/club > default -14). Returns a chain dict in set_ozone_state's
    shape. Best-effort: if a saved master/Ozone preset in the catalog matches,
    proposes reuse instead. PROPOSE ONLY - pass the returned chain to
    apply_master to write it. Returns {ok, data:{intent, parsed, target,
    true_peak, chain, decision, top_matches, reason, next}}."""
    try:
        result = _msel.recommend(intent, target=target, true_peak=true_peak)
        top_matches = []
        try:
            conn = _catalog_conn()
            _ensure_device_index(conn)
            rows = catalog_query.find_similar(conn, intent, "device_preset",
                                              limit=5)
            top_matches = [r for r in rows if _is_master_preset(r)]
            if (prefer_reuse and top_matches
                    and top_matches[0].get("score", 0) >= _msel.REUSE_MIN_SCORE):
                result["decision"] = "reuse"
                result["reason"] += " Catalog match available (reuse)."
        except Exception as e:
            logger.warning("recommend_master catalog fallback: %s", e)
        result["top_matches"] = top_matches
        result["next"] = "Pass chain to apply_master to write it."
        return _ok(result)
    except Exception as e:
        logger.error("recommend_master error: %s", e)
        return _err("recommend_master error: %s" % e)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_recommend_master_tool.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (3 tests) + clean import.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_recommend_master_tool.py
git commit -m "feat: recommend_master tool with best-effort catalog reuse"
```

---

## Task 4: apply_master MCP tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add tool after `recommend_master`)
- Test: `tests/test_apply_master_tool.py`

**Interfaces:**
- Consumes: existing `@mcp.tool()`s `set_ozone_state`, `expose_ozone_modules`, `deploy_taps` (called internally and `json.loads`-ed - same pattern as `create_from_plan` calling creators), `get_ableton_connection`, `_ok`/`_err`.
- Produces: `apply_master(ctx, chain, track_index=0, device_index=0, track_type="master", deploy_tap=True) -> str`.

- [ ] **Step 1: Write the failing test** (monkeypatch the three internal tools to return JSON strings)

```python
# tests/test_apply_master_tool.py
import json
import ableton_mcp_max.server as server


def _install_stubs(monkeypatch, sos_ok=True, tap_ok=True):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    def fake_sos(ctx, track_index, changes, device_index=0,
                 track_type="master", reload=True):
        if not sos_ok:
            return json.dumps({"ok": False,
                               "error": "device 0 on track 0 is not an Ozone 12 plugin"})
        return json.dumps({"ok": True, "data": {"reloaded": True,
                          "applied": [{"module": "Maximizer",
                                       "param": "Target Loudness [dB]",
                                       "value": -9.0}], "skipped": []}})
    def fake_expose(ctx, track_index, modules, device_index=0,
                    track_type="master", reload=True):
        return json.dumps({"ok": True, "data": {"exposed_count": 128,
                                                "overflow": []}})
    def fake_taps(ctx, track_indices=None, include_master=True):
        if not tap_ok:
            return json.dumps({"ok": True, "data": {"deployed": [],
                              "failed": [{"track_index": -1, "error": "no device"}]}})
        return json.dumps({"ok": True, "data": {"deployed": [
            {"track_index": -1, "device": "MCP Tap"}], "failed": []}})
    monkeypatch.setattr(server, "set_ozone_state", fake_sos)
    monkeypatch.setattr(server, "expose_ozone_modules", fake_expose)
    monkeypatch.setattr(server, "deploy_taps", fake_taps)


def test_apply_master_happy_path(monkeypatch):
    _install_stubs(monkeypatch)
    out = json.loads(server.apply_master(ctx=None,
                     chain={"MAX": {"Target Loudness [dB]": -9.0}}))
    assert out["ok"] is True
    d = out["data"]
    assert d["reloaded"] is True
    assert d["applied"][0]["value"] == -9.0
    assert d["exposed"]["exposed_count"] == 128
    assert d["tap"]["status"] == "deployed"
    assert "trim loop" in d["next"]


def test_apply_master_not_ozone(monkeypatch):
    _install_stubs(monkeypatch, sos_ok=False)
    out = json.loads(server.apply_master(ctx=None, chain={"MAX": {}}))
    assert out["ok"] is False
    assert "not an Ozone 12 plugin" in out["error"]


def test_apply_master_tap_failure_is_nonfatal(monkeypatch):
    _install_stubs(monkeypatch, tap_ok=False)
    out = json.loads(server.apply_master(ctx=None,
                     chain={"MAX": {"Target Loudness [dB]": -9.0}}))
    assert out["ok"] is True  # write still counts
    assert out["data"]["tap"]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_apply_master_tool.py -q`
Expected: FAIL (`apply_master` not defined).

- [ ] **Step 3: Add the tool**

```python
@mcp.tool()
def apply_master(ctx: Context, chain: dict, track_index: int = 0,
                 device_index: int = 0, track_type: str = "master",
                 deploy_tap: bool = True) -> str:
    """Apply a mastering chain (from recommend_master) to an Ozone 12 instance in
    one shot, then set up the live trim loop. Writes the chain via set_ozone_state
    (one reload, un-clamped native values), exposes the Maximizer so the skill can
    nudge ceiling/gain without further reloads, and deploys a master tap so
    measure_loudness has post-fader audio. Errors clearly if the target device is
    not Ozone 12. Returns {ok, data:{applied, skipped, reloaded, exposed, tap,
    target, next}}. deploy_tap=False skips the tap (loop then runs un-metered)."""
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        # 1. Write the chain (this also detects non-Ozone via set_ozone_state).
        sos = json.loads(set_ozone_state(ctx, track_index, chain, device_index,
                                         track_type, reload=True))
        if not sos.get("ok"):
            return _err(sos.get("error", "apply_master: chain write failed"))
        wrote = sos["data"]
        # 2. Expose the Maximizer for the reload-free live trim loop.
        exp = json.loads(expose_ozone_modules(ctx, track_index, ["MAX"],
                                              device_index, track_type))
        exposed = exp.get("data") if exp.get("ok") else {"error": exp.get("error")}
        # 3. Deploy a master tap (non-fatal on failure).
        tap = {"status": "skipped"}
        if deploy_tap:
            td = json.loads(deploy_taps(ctx, track_indices=[-1]))
            deployed = td.get("data", {}).get("deployed") if td.get("ok") else None
            tap = {"status": "deployed" if deployed else "failed",
                   "detail": td.get("data", td.get("error"))}
        return _ok({"applied": wrote.get("applied"), "skipped": wrote.get("skipped"),
                    "reloaded": wrote.get("reloaded"), "exposed": exposed,
                    "tap": tap,
                    "next": ("run the trim loop: play the densest section, "
                             "measure_loudness, nudge set_ozone_maximizer toward "
                             "target")})
    except Exception as e:
        logger.error("apply_master error: %s", e)
        return _err("apply_master error: %s" % e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_apply_master_tool.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (3 tests) + clean import.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_apply_master_tool.py
git commit -m "feat: apply_master one-shot chain write + expose + master tap"
```

---

## Task 5: Rewrite the ableton-mastering skill

**Files:**
- Modify (rewrite): `skills/ableton-mastering/SKILL.md`
- Keep as-is: `skills/ableton-mastering/loudness-targets.md`

**Interfaces:**
- Consumes: `recommend_master`, `apply_master`, `measure_loudness`, `set_ozone_maximizer`, `check_clipping`.

- [ ] **Step 1: Replace SKILL.md body** (keep the YAML frontmatter `name`/`description` - update the description to mention Ozone + recommend/apply)

```markdown
---
name: ableton-mastering
description: Finalizing a mix to a target loudness with an Ozone 12 chain, limiting, metering, and reference matching on the Ableton master. Use when mastering, hitting a LUFS target, taming true-peaks, or matching a reference loudness.
---

# Ableton mastering

Goal: hit a platform loudness target while preserving dynamics and avoiding
true-peak clipping. Master only a clean, headroom-safe mix, with Ozone 12 on the
master.

## Flow
1. Read the loudness target from the project brief. If unstated, default
   -14 LUFS / -1 dBTP and note it. See `loudness-targets.md`.
2. `recommend_master(intent, target)` -> a proposed Ozone chain (character
   bucket + target). Show the user the decision, chain summary, and target.
   PROPOSE ONLY - it writes nothing.
3. `apply_master(chain)` -> writes the chain (one reload), exposes the
   Maximizer, and deploys a master tap. If it errors "not an Ozone 12 plugin",
   tell the user to load Ozone 12 on the master first.
4. Trim loop (<= 4 iterations), all live (no reloads):
   - Jump to the densest section, `start_playback`, then `measure_loudness`.
   - If integrated LUFS is within 1 LU of target AND true-peak <= ceiling, stop.
   - Otherwise nudge `set_ozone_maximizer` live: raise `threshold` (input gain)
     to get louder; lower `ceiling` or back off gain to tame true-peak.
   - Re-measure. After 4 iterations, report the best reading and the gap.
5. `check_clipping` and confirm true-peak <= ceiling.
6. Log the target, the applied chain, and the final readings to `decisions.md`.

## Tools
- Propose/apply: `recommend_master`, `apply_master`.
- Live trim (no reload): `set_ozone_maximizer` (threshold/ceiling/character).
- Measure: `measure_loudness` (integrated LUFS / peaks), `check_clipping`.
- Direct Ozone param authoring when needed: `get_ozone_state` /
  `set_ozone_state` (native units, un-clamped) - but NOT inside the trim loop
  (they reload the set and stop playback).

## Principles
- Gain into the limiter; do not slam it. Aim for <= 3 dB gain reduction.
- Master by the meter, then by ear against a reference.
- Re-measure after every change.

## Gotchas
- `measure_loudness` needs audio actually playing through a master tap
  (apply_master deploys one; without it the loop runs un-metered - say so).
- The live `set_ozone_maximizer` path does NOT reload; use it in the loop.
  `set_ozone_state` DOES reload (stops playback) - use it only at apply time.
- Ozone-12-only: there is no native-limiter fallback in this flow.

## Checklist
- [ ] Target read from brief (or default applied + noted).
- [ ] recommend_master proposal shown before applying.
- [ ] Integrated LUFS within ~1 LU of target; true-peak <= -1 dBTP.
- [ ] Compared against a reference track.
- [ ] Logged target + chain + final readings to decisions.md.
```

- [ ] **Step 2: Verify frontmatter parses** (no code test; visual check that YAML `---` fences are intact and `name: ableton-mastering` is unchanged).

Run: `head -5 skills/ableton-mastering/SKILL.md`
Expected: shows the frontmatter with `name: ableton-mastering`.

- [ ] **Step 3: Commit**

```bash
git add skills/ableton-mastering/SKILL.md
git commit -m "docs: rewrite ableton-mastering skill for Ozone recommend/apply flow"
```

---

## Task 6: Wire /ableton:produce Master stage

**Files:**
- Modify: `commands/produce.md` (the Master stage section + the honest-limits note)

**Interfaces:**
- Consumes: `recommend_master`, `apply_master`, and the existing genre LUFS-target table already in the command.

- [ ] **Step 1: Read the current Master stage** to find its exact location.

Run: `grep -n "Master\|master\|LUFS" commands/produce.md`

- [ ] **Step 2: Replace the Master stage body** so it reads (adapt the surrounding stage-header/checkpoint wording to match the file's existing style):

```markdown
### Stage 6 - Master

1. Pull the genre's Master LUFS target from the genre table (or the brief).
2. `recommend_master(<brief text>, target=<LUFS>)` -> a proposed Ozone chain.
   Report the bucket + target to the user.
3. `apply_master(chain)` -> writes the chain, exposes the Maximizer, deploys a
   master tap. If it returns "not an Ozone 12 plugin", fall back to the
   configuration-only master pass below and mark the result un-metered.
4. Trim loop (<= 4 iters, live): play the densest section, `measure_loudness`;
   if |LUFS - target| > 1 LU or true-peak > ceiling, nudge `set_ozone_maximizer`
   live, re-measure. Stop at target +/- 1 LU.
5. Checkpoint: the stage already auto-fires playback of the densest section.

**Degrade path:** if Ozone 12 is not on the master, or no master tap can be
deployed, keep the previous configuration-only master pass and mark the master
loudness un-measured - never invent dB/LUFS.
```

- [ ] **Step 3: Update the honest-limits note** near the top of the file so the master limit reads: mastering now uses `recommend_master` + `apply_master` against Ozone 12 on the master; without Ozone or a master tap it degrades to configuration-only and is marked un-metered.

- [ ] **Step 4: Commit**

```bash
git add commands/produce.md
git commit -m "docs: wire /ableton:produce Master stage to recommend/apply_master"
```

---

## Task 7: Docs + tool-count regen (offline)

**Files:**
- Modify: `docs/index.md` (5 hardcoded count spots), `README.md` (line 7), `commands/tool-index.md`, `docs/tools/*` (regenerated)

**Interfaces:** none (documentation only). New tool count: 182 -> 184.

- [ ] **Step 1: Regenerate the auto-generated tool docs**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: `commands/tool-index.md`, `docs/tools/index.md`, and per-tool pages now show 184 tools and include `recommend_master` + `apply_master` under the mastering category.

- [ ] **Step 2: Hand-fix the hardcoded counts** the scripts do NOT touch:
  - `docs/index.md`: 5 spots (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) - change `182` -> `184`.
  - `README.md:7`: "reference for all 182 tools" -> "184 tools".

Run to find them: `grep -rn "182" docs/index.md README.md`
Expected after edit: `grep -rn "182" docs/index.md README.md` returns nothing; `grep -rn "184" docs/index.md README.md` shows the updated spots.

- [ ] **Step 3: Verify the full offline gate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
uv run python -c "import ableton_mcp_max.server"
```
Expected: all tests pass (existing 1070 + the new ~20), clean import.

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md commands/tool-index.md
git commit -m "docs: regen tool index + counts for recommend_master/apply_master (184 tools)"
```

---

## Release (CONTROLLER, after final whole-branch review + LIVE gate)

Not a subagent task. After all tasks pass review:

1. **Live gate** (main loop, needs Claude Code restart to load the new tools on AbletonDev): with Ozone 12 on the master, run `recommend_master("loud club master", target=-8)` -> `apply_master(chain)` -> one trim-loop pass; confirm the chain writes (applied non-empty, un-clamped), Maximizer exposes, a master tap is present, and `measure_loudness` moves toward the target across a `set_ozone_maximizer` nudge. Record in PROGRESS.md.
2. **Release v0.31.0:** bump `pyproject.toml` + `.claude-plugin/plugin.json`, `uv lock`; confirm docs counts (Task 7) already at 184; PR squash-merge `feat/mastering-recommend-integration`; `gh release create v0.31.0`; bump the `ableton` `ref` to v0.31.0 in `robworks-claude-code-plugins/.claude-plugin/marketplace.json`; `node scripts/build-readme.js`; push the marketplace repo. Verify the chain (local main = origin = tag; marketplace ref bumped).

---

## Plan Self-Review

- **Spec coverage:** recommend_master (Task 1+2+3), apply_master (Task 4), skill rewrite (Task 5), produce wire-in (Task 6), catalog hybrid (Task 3 best-effort layer), profile buckets + target precedence (Tasks 1-2), planning spike (Task 0), tool count 182->184 (Task 7), live gate + release (Release section). All spec sections mapped.
- **Placeholder scan:** no TBD/TODO; every code step carries full code; the one data-fill (`PARAM_KEYS` from the spike) has a defined source (Task 0) and the code is complete + testable with unconfirmed slots left `None`.
- **Type consistency:** `chain` is `{alias: {param: value}}` throughout (build_chain -> master_select.recommend -> recommend_master.data.chain -> apply_master(chain) -> set_ozone_state changes). `parse_intent` returns `{bucket,platform,keywords}` used identically in Task 2's tests and `recommend`. `REUSE_MIN_SCORE` defined in master_select (Task 2), referenced in recommend_master (Task 3). Tool signatures match their tests.
