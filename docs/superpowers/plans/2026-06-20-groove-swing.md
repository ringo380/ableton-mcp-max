# Groove & Swing for Generated Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give generated MIDI clips a real, non-faked swung feel, and determine whether true Groove-Pool assignment is reachable outside the Python LOM.

**Architecture:** A new pure module `groove_utils.py` holds the swing math (amount resolution, grid→step, off-beat delay). A new `swing_clip` MCP tool wires it through the existing `_transform_clip` apply path (`get_clip_notes` → transform → `replace_clip_notes`) — so no Remote Script change is needed for the swing feature, only a Claude Code restart. A separate gated spike (Phase 0) tests Max-LiveAPI and `.alc`-backdoor avenues for groove assignment; its verdict spawns a follow-up plan for the assignment tool.

**Tech Stack:** Python (FastMCP server, Live 3.7-era Remote Script for any handler work), pytest (offline pure-logic), `uv`.

## Global Constraints

- `*_utils.py` are imported by **server.py only** — never by the Remote Script (separate process/interpreter). Resolve/normalize/clamp on the server; send already-resolved values. (CLAUDE.md Architecture)
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`. The `/usr/bin:/bin` PATH clobber drops the `uv` pyenv shim. (CLAUDE.md Testing)
- Note dicts carry `{"start_time": float (beats), "pitch": int, "duration": float, "velocity": float, ...}`; `start_time` rounded to 6 dp by convention. Transforms are pure `list[dict] -> list[dict]` and must preserve unrelated fields (copy each note with `dict(n)`). (composition_utils.py convention)
- Pure note transforms live in their own `*_utils.py` and apply via `_transform_clip(track_index, clip_index, fn)` (server.py:208). Reuse it — do not write a new read/write path.
- Editing `server.py` or any module it imports requires a **Claude Code restart** to load (MCP server loads at session start; no hot-reload). New MCP tools arrive as deferred tools → load via `ToolSearch select:mcp__AbletonDev__<name>`. (CLAUDE.md Restart protocol)
- No AI attribution in any commit message. Use standard hyphen `-` only, never em/en-dashes. (User global rules)
- Offline gate before "done": pytest + `uv run python -c "import ableton_mcp_max.server"` (server import) + `uv run python -m py_compile remote_script/AbletonMCP/__init__.py` if the handler is touched. No CI in repo; do not reformat existing files.

---

### Task 1: `groove_utils.py` pure swing math

**Files:**
- Create: `ableton_mcp_max/groove_utils.py`
- Test: `tests/test_groove_utils.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `resolve_swing(amount) -> float` — canonical swing fraction in `[0.0, 1.0]`. Accepts a float/int OR a string. `amount` in `[0.0, 1.0]` (and not a percent string) → used directly as the fraction. `amount > 1.0`, or a string ending in `"%"`, or an int/float ≥ 50 written as a percent → MPC-style percent mapped `fraction = (percent - 50) / 50`, clamped to `[0.0, 1.0]`. Raises `ValueError` on non-numeric/garbage input.
  - `grid_to_step(grid) -> float` — beats per grid step. `"1/8" -> 0.5`, `"1/16" -> 0.25`. Raises `ValueError` on any other value.
  - `swing_notes(notes, step, fraction, tolerance=None) -> list[dict]` — pure. For each note at `start_time t`: `k = round(t / step)`; if `abs(t - k*step) <= tolerance` and `k` is odd, new `start_time = round(t + fraction * (step / 2), 6)`; otherwise the note is copied unchanged. `tolerance` defaults to `step * 0.5` (every note snaps to the nearest step — the predictable default for on-grid generated parts). All other note fields preserved.

**Disambiguation rule (exact):** treat `amount` as a percent when it is a string containing `"%"`, OR a number `> 1.0`. Otherwise (number in `[0.0, 1.0]`) treat as a direct fraction. So `0.3 -> 0.3`, `60 -> 0.2`, `"66%" -> 0.32`, `75 -> 0.5`, `50 -> 0.0`, `100 -> 1.0` (clamped), `40 -> 0.0` (clamped from `-0.2`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_groove_utils.py
import pytest
from ableton_mcp_max import groove_utils as g


def test_resolve_swing_direct_fraction():
    assert g.resolve_swing(0.0) == 0.0
    assert g.resolve_swing(0.3) == pytest.approx(0.3)
    assert g.resolve_swing(1.0) == 1.0


def test_resolve_swing_mpc_percent_number():
    assert g.resolve_swing(50) == 0.0
    assert g.resolve_swing(60) == pytest.approx(0.2)
    assert g.resolve_swing(66) == pytest.approx(0.32)
    assert g.resolve_swing(75) == pytest.approx(0.5)


def test_resolve_swing_percent_string():
    assert g.resolve_swing("66%") == pytest.approx(0.32)
    assert g.resolve_swing("50%") == 0.0


def test_resolve_swing_clamps():
    assert g.resolve_swing(100) == 1.0      # (100-50)/50 = 1.0
    assert g.resolve_swing(200) == 1.0      # over-range clamps to 1
    assert g.resolve_swing(40) == 0.0       # (40-50)/50 = -0.2 -> 0
    assert g.resolve_swing("40%") == 0.0


def test_resolve_swing_rejects_garbage():
    with pytest.raises(ValueError):
        g.resolve_swing("loads")


def test_grid_to_step():
    assert g.grid_to_step("1/8") == 0.5
    assert g.grid_to_step("1/16") == 0.25
    with pytest.raises(ValueError):
        g.grid_to_step("1/4")


def test_swing_notes_delays_offbeats_only():
    # 1/16 grid (step 0.25): k=0,1,2,3 at t=0,0.25,0.5,0.75; odd k (1,3) swung.
    notes = [
        {"pitch": 60, "start_time": 0.0, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.25, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.5, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.75, "duration": 0.25, "velocity": 100},
    ]
    out = g.swing_notes(notes, step=0.25, fraction=0.5)
    starts = [n["start_time"] for n in out]
    # on-beats unchanged, off-beats delayed by 0.5 * (0.25/2) = 0.0625
    assert starts == [0.0, 0.3125, 0.5, 0.8125]


def test_swing_notes_preserves_other_fields_and_offgrid():
    notes = [
        {"pitch": 62, "start_time": 0.25, "duration": 0.5, "velocity": 80},
        {"pitch": 64, "start_time": 0.30, "duration": 0.5, "velocity": 80},  # off-grid
    ]
    out = g.swing_notes(notes, step=0.25, fraction=1.0, tolerance=0.02)
    # first is on a step (k=1, odd) -> delayed by 0.125; second is off-grid -> unchanged
    assert out[0]["start_time"] == 0.375
    assert out[0]["pitch"] == 62 and out[0]["duration"] == 0.5 and out[0]["velocity"] == 80
    assert out[1]["start_time"] == 0.30


def test_swing_notes_zero_fraction_is_identity():
    notes = [{"pitch": 60, "start_time": 0.25, "duration": 0.25, "velocity": 100}]
    out = g.swing_notes(notes, step=0.25, fraction=0.0)
    assert out[0]["start_time"] == 0.25
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_utils.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.groove_utils'`.

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/groove_utils.py
"""Pure swing/groove helpers. Imported by server.py only (never the Remote
Script). Resolves a user-facing swing amount to a canonical fraction and bakes
off-beat delay into note start-times. See issue #27."""

_GRID_STEPS = {"1/8": 0.5, "1/16": 0.25}


def resolve_swing(amount):
    """Map a swing `amount` to a canonical fraction in [0.0, 1.0].

    - number in [0.0, 1.0]      -> direct fraction (0 = straight, 1 = max).
    - number > 1.0, or "<n>%"   -> MPC-style percent: (percent - 50) / 50.
    Result is clamped to [0.0, 1.0]. Raises ValueError on non-numeric input.
    """
    is_percent = False
    if isinstance(amount, str):
        s = amount.strip()
        if s.endswith("%"):
            is_percent = True
            s = s[:-1].strip()
        try:
            value = float(s)
        except ValueError:
            raise ValueError("swing amount must be a number or percent string, got %r" % amount)
    else:
        try:
            value = float(amount)
        except (TypeError, ValueError):
            raise ValueError("swing amount must be a number, got %r" % (amount,))

    if is_percent or value > 1.0:
        fraction = (value - 50.0) / 50.0
    else:
        fraction = value
    return max(0.0, min(1.0, fraction))


def grid_to_step(grid):
    """Beats per grid step. Accepts '1/8' (0.5) or '1/16' (0.25)."""
    try:
        return _GRID_STEPS[grid]
    except KeyError:
        raise ValueError("grid must be one of %s, got %r" % (sorted(_GRID_STEPS), grid))


def swing_notes(notes, step, fraction, tolerance=None):
    """Delay off-beat notes by `fraction * step/2`. Pure: returns new dicts.

    A note at start_time t is on grid step k = round(t/step). If it sits within
    `tolerance` of that step and k is odd (an off-beat), it is delayed; all other
    notes pass through unchanged. `tolerance` defaults to step*0.5 (snap every
    note — the predictable default for on-grid generated parts).
    """
    if tolerance is None:
        tolerance = step * 0.5
    delay = fraction * (step / 2.0)
    out = []
    for n in notes:
        m = dict(n)
        t = float(n.get("start_time", 0.0))
        k = round(t / step)
        if abs(t - k * step) <= tolerance and k % 2 == 1:
            m["start_time"] = round(t + delay, 6)
        out.append(m)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_groove_utils.py`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/groove_utils.py tests/test_groove_utils.py
git commit -m "feat(groove): pure swing math (resolve_swing, grid_to_step, swing_notes)"
```

---

### Task 2: `swing_clip` MCP tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add a `groove_utils` import near the other `*_utils` imports; add the `@mcp.tool() swing_clip` next to the other clip-note tools, after `humanize_clip` ~line 2625)
- Test: covered by the offline server-import gate + a live manual check (no new pytest; the tool is a thin wrapper over the unit-tested `groove_utils` + the existing `_transform_clip`).

**Interfaces:**
- Consumes: `groove_utils.resolve_swing`, `groove_utils.grid_to_step`, `groove_utils.swing_notes` (Task 1); `_transform_clip` (server.py:208); `_ok` / `_err` helpers.
- Produces: MCP tool `swing_clip(track_index, clip_index, amount, grid="1/16")` returning an `_ok` payload `{"notes": <int>, "grid": <str>, "swing_fraction": <float>}`.

- [ ] **Step 1: Add the import**

Find the block of `from .X_utils import ...` / `import ... as comp` lines near the top of `server.py` (where `composition_utils`, `clip_utils`, etc. are imported) and add:

```python
from ableton_mcp_max import groove_utils as groove
```

(Match the exact import style already used in that block — if the file uses `from . import composition_utils as comp`, mirror that form instead.)

- [ ] **Step 2: Add the tool**

Insert after `humanize_clip` (ends ~line 2625). Mirror the structure of `humanize_clip`/`quantize_clip_to_scale`:

```python
@mcp.tool()
def swing_clip(
    ctx: Context, track_index: int, clip_index: int,
    amount: Union[float, int, str], grid: str = "1/16",
) -> str:
    """Apply swing (shuffle) to a clip by delaying off-beat notes. Bakes a real,
    non-faked swung feel into already-generated notes; reversible with `undo`.

    Parameters:
    - track_index / clip_index: locate the clip
    - amount: swing strength. A fraction 0.0-1.0 (0 = straight, 1 = max), OR an
      MPC-style percent (50 = straight, 66 ~ triplet, 75 = max) passed as a
      number > 1 or a string like "66%".
    - grid: swing grid, "1/8" or "1/16" (default "1/16"). Off-beat steps on this
      grid are delayed; on-beats are left in place.

    Works best on grid-quantized parts (generated basslines, drums, melodies).
    """
    try:
        fraction = groove.resolve_swing(amount)
        step = groove.grid_to_step(grid)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: groove.swing_notes(ns, step, fraction))
        return _ok({"notes": count, "grid": grid, "swing_fraction": fraction})
    except Exception as e:
        logger.error("Error swinging clip: %s", e)
        return _err("Error swinging clip: %s" % e)
```

Verify `Union` is already imported at the top of `server.py` (it is used by `set_groove_amount`). If not, add `from typing import Union`.

- [ ] **Step 3: Offline gate — server imports cleanly**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0 (no `SyntaxError`/`ImportError`).

- [ ] **Step 4: Run the full offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS (existing suite + the 9 new groove tests; no regressions).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(groove): add swing_clip tool"
```

- [ ] **Step 6: Live verification (manual, after a Claude Code restart)**

After restarting Claude Code, load the tool: `ToolSearch select:mcp__AbletonDev__swing_clip`. With Live open and a grid-quantized MIDI clip present:
1. `get_clip_notes` on the target clip — record original `start_time`s.
2. `swing_clip(track_index, clip_index, amount="66%", grid="1/16")`.
3. `get_clip_notes` again — confirm odd-step (off-beat) notes moved later by ~0.0825 beats (0.32 * 0.125) and on-beats are unchanged.
4. `undo` and re-read to confirm restoration.
Record the result in `PROGRESS.md`.

---

### Task 3: Phase 0 groove-assignment spike (gated investigation)

This is an exploratory spike, not a TDD task. Its hard deliverable is a written verdict (in `PROGRESS.md` and as a comment on issue #27) plus, if the Max path works, a saved probe device. It does **not** block Tasks 1-2 or Task 4's swing-tool docs. Requires Live open via the `AbletonDev` (working-tree) MCP.

**Files:**
- Possibly Create: a minimal M4L LiveAPI probe device under the repo's Max assets dir (only if sub-probe B is attempted via a new device).
- Modify: `PROGRESS.md` (record verdict).

- [ ] **Step 1: Sub-probe A — can the Groove Pool be populated programmatically?**

With Live open, use `get_browser_tree` / `get_browser_items_at_path` to locate a factory `.agr` groove (e.g. under a "Grooves" browser folder). Attempt `load_browser_item` / `load_preset` on it and observe whether a new entry appears — read it back by issuing a Remote-Script probe that returns `len(song.groove_pool.grooves)` and each groove's `.name` (a one-off inline read in `_process_command`, or via an existing diagnostic path). Record: does browser-load add to the pool?

- [ ] **Step 2: Sub-probe B — can Max assign a groove the Python layer cannot?**

Stand up a minimal M4L device whose JS issues, against the target clip's LiveAPI object:
- `live.path` to the clip (`live_set tracks N clip_slots M clip`),
- read a groove id from `live_set groove_pool grooves`,
- send `set groove <groove_id>` to a `live.object` pointed at the clip, and a `call`-style variant if `set` is rejected,
- report the result string back (over the existing node bridge or to the Max console).

Observe whether `Clip.has_groove` flips to true / the Groove chooser in Live's UI shows the groove. Record the exact message that worked or the error returned.

- [ ] **Step 3: Record the verdict and decide the gate**

Write the outcome to `PROGRESS.md` and post it as a comment on issue #27 (no AI attribution):
- Max `set groove` **works** → the follow-up plan builds `assign_groove_to_clip` on the Max path.
- Max path **fails** → the follow-up plan reverses the `.alc` groove XML via save-diff and builds the file-based backdoor.
Then **stop** — Phase 2 (the assignment tool itself) is a separate spec+plan to be written once this gate resolves. Do not build the assignment tool in this plan.

- [ ] **Step 4: Commit any probe artifact + notes**

```bash
git add PROGRESS.md  # plus the probe device if one was saved
git commit -m "chore(groove): record Phase 0 groove-assignment spike verdict (#27)"
```

---

### Task 4: Documentation

**Files:**
- Modify: `commands/best-practices.md` (or the `/ableton:best-practices` skill source — confirm the path with `git ls-files | grep -i best-practices`)
- Modify: `commands/produce.md` (the `/ableton:produce` source — confirm path with `git ls-files | grep -i produce`)
- Modify: regenerate tool docs (see steps)

- [ ] **Step 1: Document swing vs groove honestly in best-practices**

In the best-practices source, add a short note: `swing_clip` bakes real swing into clip notes (the recommended way to swing generated parts); `set_swing_amount` only affects future quantize/add ops; groove-pool *assignment* status is per the Phase 0 verdict. Use plain `-`, no em-dashes.

- [ ] **Step 2: Update the produce command**

In the produce source, replace the inline "swing is a limitation" note with: use `swing_clip` to add shuffle to straight generated parts; note the groove-assignment status from Phase 0.

- [ ] **Step 3: Regenerate the tool index/docs**

Run the doc generators (they auto-count tools and regen the tables):

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```

Then hand-edit the hardcoded tool/category counts in `docs/index.md` (5 spots: description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) to match the new total (previous total was 136; adding `swing_clip` makes it 137 — verify the generated count and use the real number).

- [ ] **Step 4: Verify docs build + commit**

Run: `git status` — confirm only intended doc/command files changed. Spot-check `commands/tool-index.md` and `docs/tools/index.md` now list `swing_clip`.

```bash
git add commands/ docs/
git commit -m "docs(groove): document swing_clip and groove-assignment status (#27)"
```

---

## Self-Review

**Spec coverage:**
- Phase 0 spike (sub-probes A + B, decision gate, documented verdict) → Task 3. ✔
- Phase 1 swing tool (dual MPC/fraction resolver, grid→step, off-beat delay math, extended-note apply path, unit tests) → Tasks 1-2. ✔
- Phase 2 assignment tool → intentionally deferred to a follow-up plan gated on Task 3's verdict (per spec "Detailed design deferred until Phase 0 resolves"). ✔ (noted in Task 3 Step 3)
- Phase 3 docs (best-practices, produce, docstrings, tool-index regen, hardcoded counts) → Task 4. ✔

**Placeholder scan:** No "TBD"/"add error handling"/"write tests for the above" — all code and tests are concrete. `.agr` browser path and exact best-practices/produce file paths are flagged as "confirm with `git ls-files`" because they are discovery steps, not placeholders for logic.

**Type consistency:** `resolve_swing`, `grid_to_step`, `swing_notes` signatures are identical in Task 1's Interfaces block, the implementation, and Task 2's call site. The `swing_clip` return payload keys (`notes`, `grid`, `swing_fraction`) match between the tool body and its Interfaces block. Note-dict field names (`start_time`, `pitch`, `duration`, `velocity`) match the composition_utils convention.

**Notes:** Tasks 1, 2, 4 are server-only — no Remote Script change, so only a Claude Code restart (no Live reinstall) is needed before the Task 2 live check. Task 3 is independent and may run in parallel with Task 4.
