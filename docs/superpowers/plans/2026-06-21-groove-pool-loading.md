# Groove Pool Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `load_groove_to_pool(name_or_path)` (makes a factory/User `.agr` appear in `get_groove_pool`) and `search_grooves(query, limit, sources)` (discovery), via the proven `.alc` clip-embed backdoor.

**Architecture:** A new pure `groove_preset_utils.py` (server-only, unit-tested) transforms a factory `.agr` into a Groove-Pool `<Groove>` entry and injects it into a factory `.alc` wrapper. `server.py` writes the carrier `.alc` to the User Library, loads it onto a scratch track (Live merges the groove into the pool), then deletes the scratch track. No Remote Script changes — reuses existing `load_browser_item` / `create_midi_track` / `delete_track` / `get_groove_pool` handlers.

**Tech Stack:** Python 3 (server side), stdlib `gzip`/`re`/`glob`/`os`, pytest, FastMCP `@mcp.tool()`.

## Global Constraints

- **Pure helpers are server-only** — `groove_preset_utils.py` is imported by `server.py` only; the Remote Script (Live's embedded Python) CANNOT import it. Resolve/transform on the server; send already-resolved values.
- **No new Remote Script handler** — therefore no `install_remote_script.sh` + Live bounce; but a **Claude Code restart** is required to load the new server tools + module (MCP loads at session start; pure-helper edits don't hot-reload).
- **Offline gate:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`, plus `uv run python -c "import ableton_mcp_max.server"` and `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`. Do NOT reformat existing files to ruff style.
- **Preset-XML regex:** real `.agr`/`.alc` are multi-line/indented — block-matching regexes MUST use `re.DOTALL`/`re.S`. XML-escape/unescape display names (`&`/`<`/`>`).
- **Removal is infeasible** (runtime-confirmed: read-only `Vector`, no delete method) — handled by skip-on-duplicate + docstrings, NOT a tool. See the spec's "Groove-Pool Removal" section.
- **No AI attribution** in any commit message (public repo).
- Version bump target: **v0.16.0** (139 → 141 tools).

**Reference:** spec at `docs/superpowers/specs/2026-06-21-groove-pool-loading-design.md`.

---

### Task 1: `.agr` → pool-`<Groove>` transform + pool-name extraction

**Files:**
- Create: `ableton_mcp_max/groove_preset_utils.py`
- Test: `tests/test_groove_preset_utils.py`

**Interfaces:**
- Produces:
  - `groove_pool_name(agr_xml: str) -> str` — the groove's internal `<Name>` (what the pool displays), XML-unescaped.
  - `agr_to_pool_groove(agr_xml: str, groove_id: int = 0) -> str` — returns a `<Groove Id="N">…</Groove>` string: the `.agr`'s `<Groove>` inner content with the Groove-level `<LomId>` dropped and the Live-11 cosmetic nodes (`ScaleInformation`, `IsInKey`, `NoteSpellingPreference`, `PreferFlatRootNote`, `NoteEditorFoldOutZoom`, `NoteEditorFoldOutScroll`, `NoteEditorFoldScaleZoom`, `NoteEditorFoldScaleScroll`) stripped.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_groove_preset_utils.py
import os, re, glob, gzip, pytest
from ableton_mcp_max import groove_preset_utils as gpu

SYNTH_AGR = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Ableton MajorVersion="5" MinorVersion="11.0_423">\n'
    '  <Groove>\n'
    '    <LomId Value="0" />\n'
    '    <Name Value="Test &amp; Feel" />\n'
    '    <Clip>\n'
    '      <Value>\n'
    '        <MidiClip Id="0" Time="0">\n'
    '          <ScaleInformation>\n'
    '            <RootNote Value="0" />\n'
    '            <Name Value="Major" />\n'
    '          </ScaleInformation>\n'
    '          <IsInKey Value="false" />\n'
    '          <Notes><KeyTracks /></Notes>\n'
    '        </MidiClip>\n'
    '      </Value>\n'
    '    </Clip>\n'
    '  </Groove>\n'
    '</Ableton>\n'
)

def test_groove_pool_name_unescapes():
    assert gpu.groove_pool_name(SYNTH_AGR) == "Test & Feel"

def test_agr_to_pool_groove_sets_id_and_keeps_name():
    out = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=3)
    assert out.startswith('<Groove Id="3">')
    assert out.rstrip().endswith('</Groove>')
    assert '<Name Value="Test &amp; Feel" />' in out

def test_agr_to_pool_groove_drops_groove_lomid():
    # The Groove-level LomId is removed; the MidiClip body is preserved.
    out = gpu.agr_to_pool_groove(SYNTH_AGR)
    # No <LomId> as a direct child right after <Groove Id="0">
    head = out.split("<Clip>")[0]
    assert "<LomId" not in head

def test_agr_to_pool_groove_strips_cosmetic_nodes():
    out = gpu.agr_to_pool_groove(SYNTH_AGR)
    for tag in ("ScaleInformation", "IsInKey"):
        assert tag not in out
    assert "<Notes>" in out  # groove-defining data preserved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py`
Expected: FAIL (module `groove_preset_utils` not found).

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/groove_preset_utils.py
"""Pure helpers for the groove-pool .alc clip-embed backdoor (issue #36).

Server-only (Live's embedded Python cannot import this). A factory .agr is
plain XML <Ableton><Groove><Name><Clip><Value><MidiClip>; this transforms its
<Groove> into a project GroovePool <Groove Id="N"> entry and injects it into a
factory .alc wrapper. See docs/.../2026-06-21-groove-pool-loading-design.md.
"""
import re

# Live-11 .agr MidiClips carry these cosmetic nodes; a Live-12 LiveSet groove
# schema REJECTS them ("corrupt ... Unexpected value for int node: Major").
# They are presentation-only (not groove-defining), so stripping is safe on
# both versions.
_COSMETIC_TAGS = (
    "ScaleInformation", "IsInKey", "NoteSpellingPreference",
    "PreferFlatRootNote", "NoteEditorFoldOutZoom", "NoteEditorFoldOutScroll",
    "NoteEditorFoldScaleZoom", "NoteEditorFoldScaleScroll",
)


def _xml_unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'")
             .replace("&amp;", "&"))


def groove_pool_name(agr_xml):
    """The groove's internal <Name> (the pool's display name), unescaped."""
    m = re.search(r'<Groove>.*?<Name Value="([^"]*)"', agr_xml, re.S)
    if not m:
        raise ValueError("no <Groove><Name> in .agr XML")
    return _xml_unescape(m.group(1))


def _strip_cosmetic(xml):
    for tag in _COSMETIC_TAGS:
        xml = re.sub(r'\s*<%s[ >].*?</%s>' % (tag, tag), "", xml, flags=re.S)
        xml = re.sub(r'\s*<%s[^>]*/>' % tag, "", xml)
    return xml


def agr_to_pool_groove(agr_xml, groove_id=0):
    """Convert a factory .agr <Groove> into a GroovePool <Groove Id="N"> entry."""
    m = re.search(r'<Groove>(.*)</Groove>', agr_xml, re.S)
    if not m:
        raise ValueError("no <Groove> element in .agr XML")
    inner = m.group(1)
    # Drop the Groove-level LomId (first one, before <Clip>).
    inner = re.sub(r'\s*<LomId Value="[^"]*" />', "", inner, count=1)
    inner = _strip_cosmetic(inner)
    return '<Groove Id="%d">%s</Groove>' % (groove_id, inner)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py`
Expected: 4 passed.

- [ ] **Step 5: Add a real-factory round-trip test (guards the multi-line regex gotcha)**

```python
# append to tests/test_groove_preset_utils.py
def _factory_agr():
    hits = glob.glob("/Applications/Ableton*Live*.app/Contents/App-Resources/"
                     "Core Library/Grooves/**/*.agr", recursive=True)
    return hits[0] if hits else None

@pytest.mark.skipif(_factory_agr() is None, reason="no factory .agr installed")
def test_real_factory_agr_round_trip():
    xml = open(_factory_agr(), encoding="utf-8").read()
    name = gpu.groove_pool_name(xml)
    assert name and "<" not in name
    entry = gpu.agr_to_pool_groove(xml, groove_id=0)
    assert entry.startswith('<Groove Id="0">')
    for tag in ("ScaleInformation", "IsInKey"):
        assert tag not in entry
    assert "<Notes>" in entry  # real grooves carry note timing
```

- [ ] **Step 6: Run + commit**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py`
Expected: 5 passed (or 4 passed + 1 skipped if no Live installed).

```bash
git add ableton_mcp_max/groove_preset_utils.py tests/test_groove_preset_utils.py
git commit -m "feat(groove): .agr -> pool-groove XML transform (#36)"
```

---

### Task 2: Build the device-less carrier `.alc`

**Files:**
- Modify: `ableton_mcp_max/groove_preset_utils.py`
- Test: `tests/test_groove_preset_utils.py`

**Interfaces:**
- Consumes: `agr_to_pool_groove` (Task 1).
- Produces:
  - `build_carrier_alc(wrapper_xml: str, groove_entry: str, groove_id: int = 0) -> str` — takes a factory `.alc` LiveSet XML (decompressed) + a `<Groove Id="N">` entry; returns decompressed LiveSet XML with: the groove injected into `<GroovePool><Grooves>`, `DefaultGrooveId` + the clip's `<GrooveSettings><GrooveId>` set to N, and `<Devices>` emptied (so loading drags in no instrument). Caller gzips the result.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_groove_preset_utils.py
WRAPPER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Ableton MajorVersion="5" MinorVersion="12.0_12402">\n'
    '  <LiveSet>\n'
    '    <Tracks><MidiTrack><DeviceChain><DeviceChain><Devices>'
    '<InstrumentGroupDevice><X/></InstrumentGroupDevice>'
    '</Devices></DeviceChain></DeviceChain></MidiTrack></Tracks>\n'
    '    <MidiClip Time="0">\n'
    '      <GrooveSettings>\n'
    '        <GrooveId Value="-1" />\n'
    '      </GrooveSettings>\n'
    '    </MidiClip>\n'
    '    <GroovePool>\n'
    '      <LomId Value="0" />\n'
    '      <Grooves />\n'
    '      <DefaultGrooveId Value="-1" />\n'
    '      <GroovesListWrapper LomId="0" />\n'
    '    </GroovePool>\n'
    '  </LiveSet>\n'
    '</Ableton>\n'
)

def test_build_carrier_injects_groove_and_refs():
    entry = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=0)
    out = gpu.build_carrier_alc(WRAPPER, entry, groove_id=0)
    assert "<Grooves>" in out and "<Grooves />" not in out
    assert '<Groove Id="0">' in out
    assert '<DefaultGrooveId Value="0" />' in out
    assert '<GrooveId Value="0" />' in out
    assert '<GrooveId Value="-1" />' not in out

def test_build_carrier_empties_devices():
    entry = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=0)
    out = gpu.build_carrier_alc(WRAPPER, entry, groove_id=0)
    assert "InstrumentGroupDevice" not in out
    assert "<Devices />" in out or "<Devices></Devices>" in out
```

- [ ] **Step 2: Run to verify fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py -k build_carrier`
Expected: FAIL (`build_carrier_alc` not defined).

- [ ] **Step 3: Implement**

```python
# append to ableton_mcp_max/groove_preset_utils.py
def build_carrier_alc(wrapper_xml, groove_entry, groove_id=0):
    """Inject `groove_entry` into a factory .alc LiveSet so loading it merges
    the groove into the project Groove Pool. Empties device chains so the load
    drags in no instrument. Returns decompressed XML (caller gzips)."""
    out = wrapper_xml
    # 1. Replace the (empty) pool's <Grooves .../> with our groove.
    new_grooves = "<Grooves>\n%s\n</Grooves>" % groove_entry
    out, n = re.subn(r'<Grooves\s*/>', new_grooves, out, count=1)
    if not n:
        out = re.sub(r'<Grooves>.*?</Grooves>', new_grooves, out, count=1,
                     flags=re.S)
    # 2. Point DefaultGrooveId + every clip GrooveSettings at the groove.
    out = re.sub(r'<DefaultGrooveId Value="-?\d+" />',
                 '<DefaultGrooveId Value="%d" />' % groove_id, out, count=1)
    out = re.sub(r'(<GrooveSettings>\s*<GrooveId Value=")-?\d+("\s*/>)',
                 r'\g<1>%d\g<2>' % groove_id, out, flags=re.S)
    # 3. Empty all device chains so no instrument loads onto the carrier track.
    out = re.sub(r'<Devices>.*?</Devices>', '<Devices />', out, flags=re.S)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py -k build_carrier`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/groove_preset_utils.py tests/test_groove_preset_utils.py
git commit -m "feat(groove): build device-less carrier .alc with embedded groove (#36)"
```

---

### Task 3: Groove source resolution + discovery listing

**Files:**
- Modify: `ableton_mcp_max/groove_preset_utils.py`
- Test: `tests/test_groove_preset_utils.py`

**Interfaces:**
- Produces:
  - `list_grooves(roots, query="", limit=50) -> list[dict]` — `roots` is a list of `(dir, source_label)`; walks each for `*.agr`, OR-matches space-separated `query` terms against filename+folder (empty query matches all), returns up to `limit` rows `{name, file, category, path, source}` (`name` = filename stem, `category` = immediate parent folder, `file` = basename).
  - `resolve_groove_source(name_or_path, roots) -> str` — if `name_or_path` is an existing `.agr` path, returns it; else case-insensitively matches the filename stem across `roots`. Exactly one match → its path; multiple → `ValueError` listing candidate names; none → `ValueError` with the closest names.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_groove_preset_utils.py
def _mk_groove_tree(tmp_path):
    d = tmp_path / "Grooves" / "Style"
    d.mkdir(parents=True)
    for n in ("Rock Fatback 16ths", "Disco Live Feel 16ths", "Swing 8ths"):
        (d / (n + ".agr")).write_text("<Ableton><Groove/></Ableton>")
    return [(str(tmp_path / "Grooves"), "factory")]

def test_list_grooves_query_or_match(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    rows = gpu.list_grooves(roots, query="disco swing")
    names = {r["name"] for r in rows}
    assert names == {"Disco Live Feel 16ths", "Swing 8ths"}
    assert all(r["category"] == "Style" and r["source"] == "factory" for r in rows)

def test_list_grooves_empty_query_all_and_limit(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    assert len(gpu.list_grooves(roots, query="")) == 3
    assert len(gpu.list_grooves(roots, query="", limit=2)) == 2

def test_resolve_single_match(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    p = gpu.resolve_groove_source("rock fatback 16ths", roots)
    assert p.endswith("Rock Fatback 16ths.agr")

def test_resolve_existing_path_passthrough(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    direct = roots[0][0] + "/Style/Swing 8ths.agr"
    assert gpu.resolve_groove_source(direct, roots) == direct

def test_resolve_no_match_raises(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    with pytest.raises(ValueError):
        gpu.resolve_groove_source("nonexistent groove", roots)

def test_resolve_multi_match_raises(tmp_path):
    d = tmp_path / "Grooves" / "A"; d.mkdir(parents=True)
    d2 = tmp_path / "Grooves" / "B"; d2.mkdir(parents=True)
    (d / "Swing.agr").write_text("x"); (d2 / "Swing.agr").write_text("x")
    roots = [(str(tmp_path / "Grooves"), "factory")]
    with pytest.raises(ValueError):
        gpu.resolve_groove_source("swing", roots)
```

- [ ] **Step 2: Run to verify fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py -k "list_grooves or resolve"`
Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement**

```python
# append to ableton_mcp_max/groove_preset_utils.py
import os


def _walk_agr(roots):
    """Yield (path, name, category, source) for every .agr under each root."""
    for root, source in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".agr"):
                    path = os.path.join(dirpath, fn)
                    yield (path, os.path.splitext(fn)[0],
                           os.path.basename(dirpath), source)


def list_grooves(roots, query="", limit=50):
    terms = [t for t in query.lower().split() if t]
    rows = []
    for path, name, category, source in _walk_agr(roots):
        hay = (name + " " + category).lower()
        if terms and not any(t in hay for t in terms):
            continue
        rows.append({"name": name, "file": os.path.basename(path),
                     "category": category, "path": path, "source": source})
    rows.sort(key=lambda r: r["name"].lower())
    return rows[:limit]


def resolve_groove_source(name_or_path, roots):
    if name_or_path.lower().endswith(".agr") and os.path.isfile(name_or_path):
        return name_or_path
    want = name_or_path.lower().strip()
    matches = [(p, n) for (p, n, _c, _s) in _walk_agr(roots) if n.lower() == want]
    if len(matches) == 1:
        return matches[0][0]
    if len(matches) > 1:
        raise ValueError("multiple grooves named %r: %s — pass a full .agr path"
                         % (name_or_path, sorted({n for _p, n in matches})))
    near = sorted({n for (_p, n, _c, _s) in _walk_agr(roots)
                   if want in n.lower() or n.lower() in want})[:8]
    raise ValueError("no groove matching %r%s" % (
        name_or_path, (" — did you mean: %s" % near) if near else ""))
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_preset_utils.py`
Expected: all passed (Tasks 1-3 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/groove_preset_utils.py tests/test_groove_preset_utils.py
git commit -m "feat(groove): groove source resolution + discovery listing (#36)"
```

---

### Task 4: `search_grooves` server tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `_groove_search_roots` + `search_grooves` near the groove tools ~line 3342; add `import ... groove_preset_utils as groovep` near the other utils imports ~line 129)

**Interfaces:**
- Consumes: `groove_preset_utils.list_grooves` (Task 3), existing `_app_core()`, `_user_library_dir()`.
- Produces: `_groove_search_roots(sources) -> list[(dir, label)]` (factory `<core>/Grooves`, user `<UserLib>` walked for `.agr`); `search_grooves` `@mcp.tool`.

- [ ] **Step 1: Add the import** (near line 129, with the other `*_utils` imports)

```python
from ableton_mcp_max import groove_preset_utils as groovep
```

- [ ] **Step 2: Add `_groove_search_roots` + the tool** (after `get_groove_pool`, ~line 3356)

```python
def _groove_search_roots(sources):
    """(root, label) pairs to walk for .agr grooves. 'factory' = running Live's
    Core Library/Grooves; 'user' = the configured User Library. Missing skipped."""
    roots = []
    if "factory" in sources:
        core = _app_core()
        if core:
            fac = os.path.join(core, "Grooves")
            if os.path.isdir(fac):
                roots.append((fac, "factory"))
    if "user" in sources:
        lib = _user_library_dir()
        if lib and os.path.isdir(lib):
            roots.append((lib, "user"))
    return roots


@mcp.tool()
def search_grooves(ctx: Context, query: str = "", limit: int = 50,
                   sources: list = None) -> str:
    """Search Live's groove library (.agr files) by name and category.

    There is no LOM/browser path to LIST grooves, so this filesystem-walks the
    running Live's factory Core Library/Grooves and/or the User Library. Use a
    returned `name` with `load_groove_to_pool` to add it to the Groove Pool.

    Parameters:
    - query: space-separated terms (OR) matched against name + folder. Empty
      string matches everything.
    - limit: max results (default 50).
    - sources: which trees to walk: ["factory","user"] (default both).

    Returns JSON {ok, data:{count, returned, items:[{name, file, category,
    path, source}]}}.
    """
    try:
        sources = sources or ["factory", "user"]
        roots = _groove_search_roots(sources)
        rows = groovep.list_grooves(roots, query=query, limit=limit)
        return _ok({"count": len(rows), "returned": len(rows), "items": rows})
    except Exception as e:
        logger.error(f"Error searching grooves: {str(e)}")
        return _err(f"Error searching grooves: {str(e)}")
```

(If `_ok` is not the project's success helper, mirror the return shape used by `get_groove_pool` — confirm by reading `server.py` around line 3342.)

- [ ] **Step 3: Syntax-check the server imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output (clean import).

- [ ] **Step 4: Confirm the tool is registered**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ast; t=ast.parse(open('ableton_mcp_max/server.py').read()); print('search_grooves' in [n.name for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))])"`
Expected: `True`.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(groove): search_grooves discovery tool (#36)"
```

---

### Task 5: `load_groove_to_pool` server tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `_write_user_clip` host helper near `_write_user_preset` ~line 4179; add the orchestration helper + `load_groove_to_pool` tool after `search_grooves`)

**Interfaces:**
- Consumes: `groove_preset_utils.{resolve_groove_source, groove_pool_name, agr_to_pool_groove, build_carrier_alc}`, `_groove_search_roots`, `_app_core`, `_user_library_dir`, existing wire commands `get_groove_pool` / `create_midi_track` / `set_highlighted_clip_slot` / `load_browser_item` / `delete_track`, `get_browser_items_at_path`.
- Produces: `load_groove_to_pool(name_or_path)` `@mcp.tool`.

**Orchestration (proven by the spike):** resolve `.agr` → read pool, skip if the groove's pool-name is already present → build carrier `.alc` → write to `<UserLib>/Clips/<temp>.alc` → find its browser uri → create scratch MIDI track, highlight slot 0, `load_browser_item` → re-read pool, locate the new groove → **delete the scratch track + the temp `.alc` in a `finally`** → return `{ok, groove_name, pool_index, source, pool_count}`.

- [ ] **Step 1: Add `_write_user_clip`** (near `_write_user_preset`, ~line 4179)

```python
def _write_user_clip(xml, name):
    """Gzip-write a carrier .alc to <UserLib>/Clips/<name>.alc. Returns the
    dest path. The browser indexes it under user_library/Clips."""
    lib = _user_library_dir()
    dest_dir = os.path.join(lib, "Clips")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "%s.alc" % name)
    with gzip.open(dest, "wt") as f:
        f.write(xml)
    return dest
```

- [ ] **Step 2: Write the failing test for the pure-name skip path**

The orchestration needs Live, but the duplicate-detection predicate is pure. Extract it as a helper and test it.

```python
# tests/test_groove_preset_utils.py — append
def test_pool_has_name():
    pool = [{"index": 0, "name": "Swing 16ths 66"}]
    assert gpu.pool_has_name(pool, "Swing 16ths 66") == 0
    assert gpu.pool_has_name(pool, "Rock Fatback") is None
```

Run: `... pytest -q tests/test_groove_preset_utils.py -k pool_has_name` → FAIL.

- [ ] **Step 3: Implement `pool_has_name`** in `groove_preset_utils.py`

```python
def pool_has_name(pool_grooves, name):
    """Index of the groove named `name` in a get_groove_pool 'grooves' list,
    or None. Used to skip duplicate adds (pool removal is infeasible)."""
    for g in pool_grooves:
        if g.get("name") == name:
            return g.get("index")
    return None
```

Run: `... pytest -q tests/test_groove_preset_utils.py -k pool_has_name` → PASS.

- [ ] **Step 4: Add a wrapper-finder + the orchestration tool** (after `search_grooves`)

```python
def _factory_clip_wrapper():
    """A factory .alc (running Live's bundle) to use as a carrier wrapper. Its
    header MinorVersion already matches the running Live, so no version munging
    is needed. Returns decompressed XML or raises."""
    core = _app_core()
    hits = sorted(glob.glob("%s/MIDI Clips/**/*.alc" % core, recursive=True)) if core else []
    if not hits:
        raise RuntimeError("no factory .alc wrapper found under %s/MIDI Clips" % core)
    with gzip.open(hits[0], "rt") as f:
        return f.read()


def _carrier_uri(clip_name):
    """The browser item uri for a just-written User Library clip, or None."""
    res = get_ableton_connection().send_command(
        "get_browser_items_at_path", {"path": "user_library/Clips"})
    items = res.get("items", []) if isinstance(res, dict) else []
    for it in items:
        if it.get("name") == "%s.alc" % clip_name:
            return it.get("uri")
    return None


@mcp.tool()
def load_groove_to_pool(ctx: Context, name_or_path: str) -> str:
    """Add a factory or User-Library groove (.agr) to Live's Groove Pool.

    Resolves `name_or_path` (a groove name from `search_grooves`, or a full
    .agr path), then loads it into the pool via a temporary carrier clip so
    `assign_groove_to_clip` has something to bind. Returns the groove's POOL
    name + index (the pool name is the .agr's internal name, which may differ
    from the filename).

    If a groove with that pool name is already present, this is a no-op
    (`already_present: true`) — Live offers no way to REMOVE a pool groove via
    the API, so duplicates are avoided rather than cleaned up. To remove a
    groove, right-click it in Live's Groove Pool -> Remove; unsaved sets drop
    added grooves on close.

    Parameters:
    - name_or_path: groove name (case-insensitive, from `search_grooves`) or an
      absolute .agr path.
    """
    dest = None
    scratch_index = None
    try:
        roots = _groove_search_roots(["factory", "user"])
        agr_path = groovep.resolve_groove_source(name_or_path, roots)
        agr_xml = open(agr_path, encoding="utf-8").read()
        pool_name = groovep.groove_pool_name(agr_xml)

        ableton = get_ableton_connection()
        pool = ableton.send_command("get_groove_pool", {}).get("grooves", [])
        existing = groovep.pool_has_name(pool, pool_name)
        if existing is not None:
            return _ok({"already_present": True, "groove_name": pool_name,
                        "pool_index": existing, "pool_count": len(pool),
                        "source": agr_path})

        entry = groovep.agr_to_pool_groove(agr_xml, groove_id=0)
        carrier = groovep.build_carrier_alc(_factory_clip_wrapper(), entry, 0)
        clip_name = "_mcp_groove_load"
        dest = _write_user_clip(carrier, clip_name)

        uri = _carrier_uri(clip_name)
        if not uri:
            return _err("Carrier clip written but Live hasn't indexed it yet. "
                        "Refresh the browser (right-click User Library -> "
                        "Refresh) or relaunch Live, then retry.")

        si = ableton.send_command("get_session_info", {})
        scratch_index = si.get("track_count", 0)
        ableton.send_command("create_midi_track", {"track_index": -1})
        ableton.send_command("set_highlighted_clip_slot",
                             {"track_index": scratch_index, "scene_index": 0})
        load = ableton.send_command("load_browser_item",
                                   {"track_index": scratch_index, "item_uri": uri})
        if not load.get("loaded", False):
            return _err("load_browser_item did not confirm: %s"
                        % load.get("message", ""))

        pool2 = ableton.send_command("get_groove_pool", {}).get("grooves", [])
        idx = groovep.pool_has_name(pool2, pool_name)
        return _ok({"already_present": False, "groove_name": pool_name,
                    "pool_index": idx, "pool_count": len(pool2),
                    "source": agr_path})
    except Exception as e:
        logger.error(f"Error loading groove to pool: {str(e)}")
        return _err(f"Error loading groove to pool: {str(e)}")
    finally:
        try:
            if scratch_index is not None:
                get_ableton_connection().send_command(
                    "delete_track", {"track_index": scratch_index})
        except Exception:
            pass
        try:
            if dest and os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass
```

(Confirm `_ok`/`_err` names + the `send_command` return shapes by reading `get_groove_pool`/`load_preset` in `server.py`; adjust `.get("grooves", [])` if results are nested under `data`/`result`.)

- [ ] **Step 5: Syntax-check + tool registration**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: clean.
Run: `... pytest -q` → all pure tests pass.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py ableton_mcp_max/groove_preset_utils.py tests/test_groove_preset_utils.py
git commit -m "feat(groove): load_groove_to_pool via .alc clip-embed backdoor (#36)"
```

- [ ] **Step 7: LIVE VERIFICATION (manual, after a Claude Code restart)**

Restart Claude Code (loads the 2 new tools + module). Then, against an open set:
1. `search_grooves(query="rock")` → returns factory `.agr` rows.
2. `get_groove_pool` → note count.
3. `load_groove_to_pool("Rock Fatback Accent 16ths")` → `{ok, groove_name, pool_index}`; the scratch track must NOT linger (re-read `get_session_info`).
4. `get_groove_pool` → count grew by 1, new groove present.
5. `assign_groove_to_clip(track, clip, <new pool_index>)` → confirms the groove is usable.
6. Call `load_groove_to_pool` again with the same name → `already_present: true`, count unchanged.
Record results in PROGRESS.md.

---

### Task 6: Docs, version bump, changelog

**Files:**
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json` (version → 0.16.0); `uv.lock` (via `uv lock`)
- Modify: `PROGRESS.md`; regen `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md` via `scripts/gen_docs_site.py` + `scripts/build_tool_index.py`
- Modify by hand: `docs/index.md` hero (5 hardcoded tool/category-count spots)

- [ ] **Step 1: Bump version in both files** to `0.16.0`, then `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock` to sync `uv.lock`.

- [ ] **Step 2: Regen tool docs**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && uv run python scripts/gen_docs_site.py`
Expected: tool count shows 141.

- [ ] **Step 3: Hand-edit `docs/index.md`** — update the 5 hardcoded spots (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) to 141 tools.

- [ ] **Step 4: Update `PROGRESS.md`** — record groove-pool loading shipped (v0.16.0, 141 tools), the live-verification results, and the runtime-confirmed removal-infeasibility note.

- [ ] **Step 5: Final offline gate**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q && uv run python -c "import ableton_mcp_max.server" && uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: all pass / clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: docs + version bump 0.15.0 -> 0.16.0 - groove pool loading (141 tools)"
```

---

## Release (after merge — follows the project's published flow)

PR → `gh pr merge --squash --delete-branch` → `gh release create v0.16.0` → bump `ref` in the `ableton` entry of `robworks-claude-code-plugins/marketplace.json` to v0.16.0 → `node scripts/build-readme.js` → push marketplace repo. Verify the release chain per CLAUDE.md (local `main` = `origin/main` = `git ls-remote` tag commit). Close issue #36.

## Notes for the implementer

- **Server-tool tasks (4, 5) have no offline functional test** — the project has no mock-Live harness, so their gate is `import ableton_mcp_max.server` + the pure-helper unit tests + manual live verification (Task 5 Step 7). This is the established project convention; do not invent a Live mock.
- **`_ok`/`_err` and `send_command` result shapes:** the code blocks assume helpers named `_ok`/`_err` and that `get_groove_pool` returns `{"grooves":[...]}`. Before implementing Tasks 4-5, read `server.py`'s `get_groove_pool` (~line 3342) and an existing loader to confirm the exact success-wrapper name and whether results nest under `data`/`result`; adjust the snippets to match. This is the one place the plan defers to the live code.
- **Restart discipline:** server.py + new-module edits need a **Claude Code restart** to take effect (no Live bounce — no Remote Script change).
