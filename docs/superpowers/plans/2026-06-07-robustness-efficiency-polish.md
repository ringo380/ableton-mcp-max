# Robustness, Efficiency & Polish initiative

**Created**: 2026-06-07
**Status**: In Progress (Phase A code-complete, offline-verified; live-verify pending restart)

Hardening pass over the three existing layers (socket transport, per-command efficiency,
LLM-facing tool surface). Not new features - the plugin already has broad live-verified LOM
coverage (106 tools, phases 0-11). User opted into all four tracks + a batch protocol.

Recommended order: **A → B → C → E → D**.

## Phase A - Connection robustness (server.py only; Claude Code restart, no Live bounce)
1. Transparent reconnect in `send_command`, split into send-phase vs recv-phase failures:
   send-phase failures retry once (command never reached Live, safe even for mutations);
   recv-phase failures retry once only when idempotent (reads, or explicit `idempotent=True`).
2. Removed the dead `sendall(b'')` liveness probe in `get_ableton_connection`; rely on
   send_command's reconnect-on-failure instead.
3. `MUTATING_COMMANDS` frozenset = single source of truth (was a stale 52-entry server list
   missing 24 real mutations → those skipped the settle delay and got the 10s read timeout).
   Drives both the settle delay and the timeout. A test parses the remote list and asserts equality.
4. Aligned timeouts: `_MUTATE_TIMEOUT` (15s) > remote `main_thread_task` timeout (10s) so slow ops
   surface the remote's clean timeout message.
- Tests: `tests/test_connection.py` (FakeSocket; 8 cases incl. drift guard).

## Phase B - Batch / transaction protocol (both halves; dual restart)
- Remote: `batch` command runs members in ONE main_thread_task via a shared
  `_dispatch_main_thread(command_type, params)` helper (refactor of the if/elif body); honors
  `stop_on_error`, returns ordered `[{status, result|message}]` + failure index.
- Server: `send_batch()` (one round-trip, one settle pair) + a `batch` tool; reuse it to collapse
  `load_drum_kit` and read+set name-resolution pairs.
- Guard: do NOT batch async-settle orchestrations (cue points). `batch_utils.py` validates shape,
  rejects nested batch. Offline tests.

## Phase C - Efficiency tuning (server.py + source-side limits in remote)
- Tune the 200ms settle: keep for the documented write-lag ops, trim the rest (optional
  `_SLOW_SETTLE` subset). Add `limit`/windowing to unbounded readers (`get_browser_tree`,
  `get_browser_items_at_path`, `get_arrangement_clips`) following the `list_device_presets` pattern.

## Phase D - LLM-consumer polish (server.py + a tool-index reference)
- Standardize write/action return envelopes (`_ok(action, **fields)` JSON) vs ad-hoc strings.
- One docstring template (summary / Parameters / Returns / track_type note). Surface the
  device-tool regular-track-only asymmetry in those tools' own docstrings.
- Additive param-name consistency (`track_index`/`scene_index`/`clip_index`).
- `commands/tool-index.md` taxonomy grouped by domain, regenerated via the `ast` enumerator.

## Phase E - Offline tool tests
- Mock-socket harness for tool-level marshalling, envelope, name-resolution, reconnect/idempotency.

## Verification
- Offline gate after each phase: `uv run --with pytest pytest -q`; server import; remote py_compile.
- Live gate (AbletonDev tools): A = kill+reopen Live mid-session, confirm next read auto-recovers;
  B = batch round-trip + partial-failure + timing; C = timing + capped readers; D = envelope checks.
