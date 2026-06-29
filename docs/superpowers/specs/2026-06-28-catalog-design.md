# Local Catalog + Decision Engine - Design

**Date:** 2026-06-28
**Status:** Approved (design); ready for implementation plan
**Repo:** ableton-mcp-max

## Goal

Give the MCP server persistent, cross-session awareness of the user's on-disk
content (Serum presets, samples, grooves, Ableton device presets) so the LLM can
cheaply answer "what exists" and decide reuse-vs-create before acting - and, when
it decides to create, orchestrate the existing authoring tools (propose then
confirm).

## Scope

In scope (one combined spec, built as separate internal modules):

1. **Catalog** - a persistent sqlite index of four content domains plus fast
   query tools (FTS5, lexical).
2. **Decision engine** - lexical reuse-vs-create judgment over the catalog,
   returning a structured decision plus a concrete create plan. Propose only.
3. **Orchestration** - turn a create plan into a real call to an EXISTING
   authoring tool, gated behind an explicit confirm.

Explicitly OUT of scope (deferred to its own future initiative):

- **Full Serum tree synthesis** (authoring a `.SerumPreset` from nothing:
  oscillators, wavetable frame selection, mod matrix, envelopes/LFOs, etc.).
  This is several Release-scale efforts and is unrelated to the catalog. The
  catalog will feed it cleanly when it is built.
- **Semantic / embedding search.** v1 matching is lexical (FTS5 + token
  scoring). The LLM supplies good intent strings. Embeddings can layer on later.
- **A separate always-on daemon / file watcher.** The MCP server process is
  already the long-running local host; the sqlite file is the cross-session
  store. A watcher is a future optimization, not needed here.

## Global Constraints

- New code is host-side **pure modules imported by `server.py` only**. The Remote
  Script (Live's separate Python) never imports them and needs no new handlers.
- The only new third-party dependency is **none**: Python's stdlib `sqlite3`
  ships with FTS5 in CPython.
- DB lives at `~/.ableton-mcp/catalog.db`. It is a disposable cache: created on
  first use, never shipped, safe to delete (rebuilds), never holds precious data.
- All new tools return the house envelope `{ok, data}` / `{ok, error}` via the
  existing `_ok`/`_err` helpers.
- A catalog failure must always degrade (slower / cached / clear error), never
  break a tool. Where a live path exists, fall back to it.
- ASCII only in all source, docs, commits, and PR text. No AI attribution
  anywhere (public repo).
- Offline gate: `uv run --with pytest pytest -q` + `py_compile` +
  `uv run python -c "import ableton_mcp_max.server"`. No CI; do not reformat
  existing files.

## Architecture

```
server.py (tools + orchestration dispatcher + injected browser_reader)
   |  imports
   v
catalog_decide.py   (decision engine; pure logic over query results)
   |  imports
   v
catalog_query.py    (FTS search, find_similar scoring, stats; pure given a conn)
   |  imports
   v
catalog_index.py    (per-domain indexers, freshness fingerprints)
   |  imports
   v
catalog_db.py       (sqlite lifecycle, schema, migrations, FTS5; stdlib only)
```

No module reaches back into `server.py`. Orchestration (executing a create plan)
lives in `server.py` because it must call existing tool impls and the Ableton
connection; it cannot be a pure module.

### Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `catalog_db.py` | Open/create DB at `~/.ableton-mcp/catalog.db`; schema + migrations; FTS5 setup + sync triggers; WAL mode; rebuild-on-corruption/version-mismatch. | stdlib `sqlite3` |
| `catalog_index.py` | Indexers per domain: walk roots, extract metadata (reusing `classify_sample`, `is_xml_agr`, `serum_state_codec.decode`), upsert rows, compute freshness fingerprints. Device-preset indexer takes an injected `browser_reader` callable. | `catalog_db`; existing `sample_utils`, `groove_preset_utils`, `serum_state_codec` |
| `catalog_query.py` | Read side: FTS5 search, filters, `find_similar` scoring, stats aggregation. | `catalog_db` |
| `catalog_decide.py` | Decision engine: intent -> query -> rank -> threshold -> `{decision, top_matches, create_plan, reason}`. Never writes. | `catalog_query` |

### Connection-dependent boundary

Device-preset indexing needs Live's browser. `catalog_index.index_device_presets(
db, browser_reader)` receives a callable injected by `server.py` (wrapping the
existing `get_browser_presets` command). The module stays connection-agnostic and
unit-testable with a fake reader. Same "resolve on the server, pass it in" ethos
as the rest of the codebase.

## Database Schema

`~/.ableton-mcp/catalog.db`, WAL mode, created on first use.

### `items` - one row per discovered asset (all domains share it)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `domain` | TEXT | `serum` \| `sample` \| `groove` \| `device_preset` |
| `name` | TEXT | display name (filename stem or preset name) |
| `path` | TEXT NULL | absolute fs path; NULL for device presets |
| `uri` | TEXT NULL | browser URI; NULL except device presets |
| `source` | TEXT | `factory` \| `user` |
| `folder` | TEXT | folder / category (grouping + match scoring) |
| `kind` | TEXT NULL | sample: `loop`/`one_shot`/`kit`/`instrument`; else NULL |
| `loadable` | INTEGER | 0/1; default 1 (groove XML-vs-binary, decode success) |
| `mtime` | REAL NULL | source file mtime; NULL for device presets |
| `extra` | TEXT | JSON blob for domain-specific fields (e.g. Serum `fx_types`, decoded category) |
| `indexed_at` | REAL | epoch when row written |

Uniqueness: `(domain, source, path)` for fs domains; `(domain, uri)` for device
presets. Upserts key on these.

### `items_fts` - FTS5 virtual table

Indexes `name + folder` (+ Serum decoded tags from `extra`). Kept in sync with
`items` via triggers. Backs `search_catalog` and `find_similar`. Lexical only.

### `roots` - freshness tracking

| Column | Type | Notes |
|---|---|---|
| `root_path` | TEXT | indexed root, or `lom:device_presets` sentinel |
| `domain` | TEXT | |
| `source` | TEXT | |
| `fingerprint` | TEXT | cheap dir-tree signature (see Freshness) |
| `last_indexed` | REAL | epoch |

### `meta`

`schema_version` (drives migrations) + a global last-run marker.

### Migrations

`catalog_db` checks `meta.schema_version` on open. If behind, it drops and
rebuilds (the catalog is a cache, so a version bump triggers a full reindex
rather than complex ALTERs).

## Indexing

### Roots per domain (reusing existing resolvers)

- **Serum:** `/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets/`
  recursively for `*.SerumPreset` (factory) + user Serum preset dir if present.
  Decode each via `serum_state_codec.decode`; pull name, category, and `fx_types`
  into `extra`. Undecodable files are recorded with `loadable=0` (not skipped) so
  stats stay honest.
- **Samples:** `_user_library_dir()` + `_app_core()` Samples, via `os.walk`,
  classified with existing `classify_sample` + iCloud-placeholder logic.
- **Grooves:** `_app_core()/Grooves` + user library, `.agr` only, `loadable` from
  `is_xml_agr`.
- **Device presets:** via injected `browser_reader` (existing
  `get_browser_presets`), only when Live is connected.

### Resilience

- Decode/parse failures (corrupt `.SerumPreset`, binary `.agr`) are recorded as
  `loadable=0`, never abort the index. One bad file cannot kill a full run.

## Freshness (hybrid: auto-stale + manual)

### Fingerprint

For each fs root, the fingerprint is a hash over **directories only** -
`(dirpath, dir_mtime)` for every dir under the root via `os.scandir`, never
statting individual files. Adding/removing/renaming any file bumps its parent
dir's mtime, so this catches all content changes while statting hundreds of dirs
instead of thousands of files (sub-second on a large library).

### Query-time flow

1. In-process throttle: if a root was checked < ~60s ago this session, skip the
   check (avoids re-fingerprinting on every query in a burst).
2. Else recompute the root's fingerprint; if it differs from `roots.fingerprint`,
   reindex just that root (delete its rows, re-walk, re-insert) before answering.
3. `reindex_catalog(domains=None, full=False)` forces it; `full=True` drops and
   rebuilds from scratch.

### Device-preset freshness

Cannot fingerprint a fs tree (LOM-only). Policy: index on first query of the
session and on explicit `reindex_catalog`; rows carry `indexed_at`;
`catalog_stats` reports device-preset staleness. If Live is not connected,
device-preset queries return cached rows plus `live_disconnected: true`, and
indexing is skipped with a noted reason (not an error).

### First-run cost

Initial full index walks everything once (seconds for grooves/Serum, longer for a
big sample library). `catalog_stats` and query tools trigger a lazy build if the
DB is empty; `reindex_catalog` warms it deliberately.

## Tool API

Six new tools (155 -> 161). Two existing tools change internally only (same
signatures, same return shapes).

### Query (catalog_query)

- `search_catalog(query, domains=None, kinds=None, sources=None, limit=50)` -
  FTS5 search across the index. Returns items with `count/returned/truncated`.
- `catalog_stats()` - counts by domain/source/kind; per-domain `last_indexed`;
  device-preset staleness + `live_disconnected`; total size. The LLM's
  situational-awareness call.
- `find_similar(intent, domain, limit=10)` - ranked matches **with scores** for
  one domain. The retrieval primitive the decision engine builds on; also usable
  directly.

### Decision (catalog_decide)

- `recommend_asset(intent, domain)` - runs `find_similar`, applies the
  create-threshold, returns:
  ```json
  {
    "decision": "reuse" | "create",
    "top_matches": [{"name": "...", "path": "...", "uri": "...", "score": 0.0}],
    "create_plan": {"tool": "...", "params": {}, "base_preset": "..."},
    "reason": "..."
  }
  ```
  **Propose only - never writes.** On `reuse`, `create_plan` is null. On `create`,
  it names the existing authoring tool and concrete params.

### Orchestration (server.py dispatcher)

- `create_from_plan(plan, confirm=False)` - with `confirm=False` (default) returns
  exactly what it would do (dry run). With `confirm=True` it dispatches
  `plan.tool` to the existing creator:
  - Wavetable -> `create_wavetable_preset`
  - Simpler -> `create_simpler_instrument`
  - Serum -> clone the chosen base `.SerumPreset` to the User Library under a new
    name, then apply any FX-rack edits via the Release-2 tooling. (Synth-param-in-
    file editing beyond FX is the deferred synthesis initiative - this is the
    honest v1 boundary of "base preset + param edits".)
  - samples / grooves plans are never `create` (gap report only).

### Maintenance

- `reindex_catalog(domains=None, full=False)`.

### Changed existing tools (Approach A)

`search_samples` and `search_grooves` become thin wrappers that query the catalog,
falling back to their current live walk if the DB is empty/unavailable. Same
signatures, same return shape - faster, single source of truth, no regression.

## Error Handling

- **Catalog never breaks a query.** Any catalog failure (DB locked, corrupt,
  schema mismatch, disk) is caught; query tools fall back to live behavior where
  one exists, or return `{ok:false, error}` with a clear message. A broken cache
  degrades to "slower," never "tool down."
- **Disposable-cache recovery:** on `sqlite3.DatabaseError` or schema-version
  mismatch, `catalog_db` rebuilds the file from scratch. `~/.ableton-mcp/` is
  created if missing.
- **Decode failures** recorded as `loadable=0`, never crash the indexer.
- **Live disconnected:** device-preset queries return cached rows +
  `live_disconnected:true`; device indexing skipped with a noted reason.
- **Orchestration:** `create_from_plan` reuses the existing creators' error
  handling and the `_ok`/`_err` convention; on a failed create it returns the
  underlying error and writes nothing further. Defaults to dry-run.

## Testing

Offline gate: `uv run --with pytest pytest -q` + `py_compile` + server import.

- **`catalog_db`:** schema creation; FTS5 sync triggers; migration/rebuild on
  version bump; WAL mode. In-memory + tmpdir DBs.
- **`catalog_index`:** each indexer against a synthetic tmpdir tree (fake
  `.SerumPreset` via the codec's `encode`, fake `.agr` XML + binary, fake sample
  tree); fingerprint changes when a file is added/removed/renamed; device-preset
  indexer driven by a fake `browser_reader` (no Live needed); corrupt-file ->
  `loadable=0`.
- **`catalog_query`:** FTS ranking; filters; `find_similar` scores;
  `catalog_stats` aggregation; empty-DB behavior.
- **`catalog_decide`:** reuse-vs-create threshold; `create_plan` shape per domain;
  propose-never-writes invariant.
- **Delegation parity:** `search_samples` / `search_grooves` return identical
  shapes from catalog vs. live-walk fallback.
- **Live verification (manual, post-merge, recorded in PROGRESS.md):** real index
  of the actual library; `recommend_asset` + `create_from_plan(confirm=True)`
  round-trip for Wavetable / Simpler / Serum-clone; device-preset index with Live
  running.

## Ship Convention (per CLAUDE.md)

- Version bump in `pyproject.toml` + `.claude-plugin/plugin.json` + `uv.lock`.
- Regenerate docs via `gen_docs_site.py` / `build_tool_index.py` (new "Catalog"
  category) + hand-bump the hardcoded counts in `docs/index.md` (5 spots) and
  `README.md`.
- Branch -> PR -> squash-merge -> tag -> bump marketplace `ref` +
  `build-readme.js` -> push marketplace repo.
- Verify the release chain: local main = origin/main = `git ls-remote` tag commit
  = marketplace `ref`.
