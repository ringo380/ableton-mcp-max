# ableton-mcp-max — Progress

## VST/AU plugin support (Serum 2) - IN PROGRESS: Task 0/1/2 + serum2.json pack DONE (2026-06-27)
Branch `feat/vst-plugin-support` (7 commits, clean tree, NOT pushed/PR'd yet). Spec + plan committed
under docs/superpowers/. Goal: expose, control, author 3rd-party VST3/AU plugin params via the
Configure-list XML backdoor (Serum 2 first).

**>>> RESUME HERE (2026-06-27) - serum2.json pack built (@5e6caf3); Task 3 `expose_plugin_parameters` next.**

STATE: Task 0 gate + Task 1 (encoder) + Task 2 (probe tool) DONE & committed. The Serum Configure id
scheme is RESOLVED. The user manually Configured the FULL 128-slot pool; `serum2.json` is built and
committed. NEXT = Task 3 (`expose_plugin_parameters`).

KEY RESOLVED FACTS:
- **Serum Configure ParamID = category_base + module_index*1000 + param_offset.** Bases by module TYPE
  (all CONFIRMED from the live 128 capture): global/voice ~0 (Main Vol=0, Bend Up/Down=5/6, Pitch Bend=7,
  Mod Wheel=8, Mono=10, Porta=12, Transpose=16), oscillators 1000000 (**A=mod0/B=1/C=2/Noise=3/Sub=4**),
  filters 2000000 (F1=mod0/F2=mod1; On+0/Wet+1/Type+2/Freq+3/Res+4/Drive+5/Var+6/Stereo+7/Level+8/X+9/Y+10),
  envelopes 3000000 (**Env 1-4** = +N*1000, ADHSR), LFOs 4000000 (**LFO 1-3** = +N*1000), **mod matrix
  6000000** (Mod N Amount = +N*1000), macros 7000000 (Macro N = +N*1000), routing/balance/bus 9000000,
  **clip player 10000000, arp 12000000**. NOT the get_parameter_names probe index.
- **FX IS UNREACHABLE via Configure** (confirmed): Serum does NOT expose its FX racks (FXDelay/FXComp/FXEQ/
  FXReverb/...) to the VST3 host parameter list, so they cannot be Configured/LOM-automated. FX control is a
  separate future path = `.SerumPreset` authoring (format cracked, see below).
- **`.SerumPreset` FORMAT CRACKED:** `XferJson` container = 8-byte magic "XferJson" + 1 pad + uint64 JSON-len
  + plaintext metadata JSON + a **zstd**-compressed blob (magic 28 b5 2f fd, preceded by 8-byte
  uint32-len/flags). Decompress (`zstandard`) -> **CBOR** (`cbor2`) = the FULL internal state tree:
  Oscillator0-4, VoiceFilter0/1, Env0-3, LFO0-9, FXRack0-2 (each `FX:[{type,...}]`), ModSlot0-63, Macro0-7,
  every module's `plainParams` (internal `kParam*` names). `ModSlot` entries carry destModuleID/
  destModuleParamID/destModuleParamName/destModuleTypeString = a built-in ID<->name Rosetta Stone that
  CONFIRMS the Configure formula (Noise osc destModuleID=3, kParamVolume paramID=1 -> Configure 1003001
  "Noise Level"). `.XferShape` is the same container. Decoder one-liner: find `\x28\xb5\x2f\xfd`, zstd-decompress,
  cbor2.loads. Saved decoded sample at `.vst-harvest-local/serum_preset_decoded.json`.
- **MIDI CC export = empty** (user tried Serum's "save MIDI CC map" - no CC mappings were assigned, so nothing
  written; not a bug).
- **The ORACLE / disk-parse harvest:** fill a `<PluginFloatParameter>` slot with a ParameterId + sentinel
  name, reload the set, then `save_set` -> Live persists the REAL ParameterId<->ParameterName into the
  `.als` for VALID ids (is_enabled stays false + sentinel kept for invalid). Parse the `.als` on disk = cheap.
  GOTCHA: the slot open tag is `<PluginFloatParameter Id="N">` (has an attribute) - parse regex must allow it
  (`<PluginFloatParameter\b...`); a bare `<PluginFloatParameter>` matches NOTHING.

DURABLE ARTIFACTS (survive a fresh session; scratchpad does NOT):
- **Committed:** `ableton_mcp_max/param_maps/serum2.json` (128 params, {plugin,id_base,params:[{param_id,
  name,category}]}; macros normalized to generic "Macro N") + `tests/test_param_map_utils.py` load test.
- Live test set: `/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als` - Serum 2 on track 0
  (dev 0), holding all 128 Configured params (saved). REOPEN this set in Live to continue.
- `<repo>/.vst-harvest-local/` (git-ignored, local-only): `serum2_configured_current.json` (the live 128
  id<->name pairs, raw incl. custom macro labels), `serum2_configured_76.json` (older 76 snapshot),
  `serum_preset_decoded.json` (decoded .SerumPreset CBOR), `harvest.py`/`reload.sh` (patch+reload harness),
  `harvest_findings.md`, `serum2_probe_names.json` (full 2623-name probe).
- Re-derive the live set's slots anytime: gzip-open the .als, regex `<PluginFloatParameter\b.*?</...>` (DOTALL),
  take ParameterId!=-1, html.unescape the ParameterName.

**TASK 3 OFFLINE DONE (@5b7e6fc) - LIVE VERIFY PENDING (needs a Claude Code restart):**
`expose_plugin_parameters(track_index, device_index=0, pack="serum2", track_type="regular", reload=True)`
MCP tool added. Flow (Option A): save set -> read `.als` -> `plugin_config_utils.locate_param_list`
navigates to the device_index-th plugin device's `<ParameterList>` -> `bump_next_pointee_id(count)` ->
`fill_slots` the pack params into the empty Configure slots -> `write_als` -> `_reload_set` in place.
Pure navigator `locate_param_list` (depth-aware; skips mixer-sends/nested-rack ParameterLists; rejects a
non-plugin device) + `_expose_plugin_impl` behind save/reload/IO seams. Manual default "0.5" (Live
reconciles vs the plugin on load). 13 new tests; full suite 912 passed; server import + RS compile clean.
- **Tool count will go 148 -> 149** (docs/version NOT yet bumped - that's Task 5/ship).

LIVE-VERIFY PLAN (Step 4 - DO AFTER the user restarts Claude Code so AbletonDev loads the new tool):
1. **KEY UNKNOWN to settle first:** does a FRESH (unconfigured) Serum 2 serialize empty
   `<PluginFloatParameter>` slots in its `.als`? The gate patched a pre-existing empty slot, and our
   findings say "128-slot pool", but the fully-configured test set has 0 empty slots. If a fresh device
   has 0 empty slots, `fill_slots` fills nothing -> exposure needs to APPEND slots (follow-up). Load a
   fresh Serum on a scratch MIDI track, `save_set("")`, parse the `.als` ParameterList: count empties.
2. If empties exist: `expose_plugin_parameters(track_index=<scratch>, pack="serum2")` -> reload -> 
   `get_device_parameters` should now show ~128 params; `set_device_parameter` a filter/env/osc and
   confirm the Serum knob moves + the SOUND isn't reset (verifies the Manual="0.5" no-op assumption).
3. Clean up the scratch track. Record results; then Task 5 (curation/docs/ship Release 1).

(Later / Release 2) FX control via `.SerumPreset` authoring now that the format is cracked.

COMMITTED THIS SESSION (branch feat/vst-plugin-support, NOT pushed): probe tool @6a2c846; **VST/AU URI
loader fix @ad655b6** (`_find_browser_item_by_uri` lacked the 'plugins' root - VST3/AU were unloadable by
URI; live-verified Serum 2 loads); several PROGRESS docs. RS reinstalled+bounced this session.
- **Task 1 DONE (offline, committed @2524660):** `ableton_mcp_max/plugin_config_utils.py` +
  `tests/test_plugin_config_utils.py` (11 tests): find_empty_slots / build_slot / fill_slots
  (overflow-reporting) / max_target_id / bump_next_pointee_id.
- **Task 2 OFFLINE DONE (committed @6a2c846):** RS `_probe_plugin_parameters` (full name list via
  `get_parameter_names(0,-1)`/`get_bank_parameters(-1)`, guarded) + dispatch; thin server tool
  `probe_plugin_parameters`; pure `param_map_utils` (derive_serum_ids/validate_pack/load_pack/
  find_params) + 15 tests; empty `param_maps/__init__.py`. Full suite 899 passed, 2 skipped;
  server import + RS py_compile clean. serum2.json NOT yet generated (needs the live probe).

**Make-or-break gate PASSED (Live 12.4 Suite):** an EXTERNALLY-written Configure slot becomes a
live, named, settable LOM `DeviceParameter`. Method: patched one empty `<PluginFloatParameter>`
slot in a saved `.als` (ParameterId=2000007, Manual=0.5), reloaded → `get_device_parameters`
showed param_count 6 incl. a new control Live resolved to "Filter 1 Stereo"; `set_device_parameter`
to 0.9 moved Serum's knob in the GUI (user-confirmed). Full LOM control of plugin knobs is real.

**Key findings:**
- **Default exposure = nothing.** Serum 2 (both AU `AuPluginDevice` and VST3 `PluginDevice`)
  exposes only `Device On` until params are Configured. No LOM API to Configure (confirmed); the
  commercial Serumify product also requires manual Configure "up to 128 params" (matches the
  128-slot pool we found).
- **Slot encoding (save-diff):** fill `<PluginFloatParameter>` with `ParameterId` (real VST3 id),
  `ParameterName`, `Manual` (native units; LOM reads/sets normalized 0-1), `VisualIndex`. Empty
  sentinels: ParameterId=-1, Manual=0.1234567687, VisualIndex=1073741823.
- **CORRUPTION RULE:** Live keeps a global `<NextPointeeId>` that MUST exceed every
  `AutomationTarget`/`ModulationTarget` Id. Allocate the slot's two target ids FROM NextPointeeId
  and advance it by 2, else load fails ("NextPointeeId is too low: N must be bigger than M").
- **Discovery formula confirmed:** `id = 2000000 + plugin_param_index` (2000007 → "Filter 1
  Stereo", index 7; Filter 1 block = Freq3/Res4/Drive5/Var6/Stereo7).
- **Delivery model - corrected:** Live 12 will NOT mint a VST3 `.adv` (both Save-Preset and
  drag-to-browser produce a `.vstpreset` = plugin binary state only, no ParameterList); a
  hand-synthesized `.adv` failed to load. So **Option B-via-`.adv` is DEAD for VST3.**
  - **Option A (live-set `.als` patch): PROVEN.** Serum stays a TOP-LEVEL device → exposed params
    directly reachable by existing get/set_device_parameter. Cost: one set save+reload per
    instance to expose.
  - **Option B-via-rack `.adg`: viable but nests.** A rack `.adg` DOES carry the exposure (as
    compact `<PluginParameterSettings>`: Index/VisualIndex/ParameterId/Type) AND the plugin state
    (ProcessorState/ControllerState/Vst3Preset); loads via browser with NO set reload. BUT Serum
    sits nested in the rack chain → its exposed params are NOT on `track.devices[0]` (that's the
    rack: 16 macros + chain selector), so reaching them needs chain-aware param access the current
    tools lack. No `NextPointeeId` needed in `.adg` (preset target ids are all 0).
- **DELIVERY DECISION = C (user-chosen):** Release 1 = Option A (live-set `.als` patch, top-level
  Serum, proven, existing get/set tools, one save+reload per instance). Release 2 fast-follow =
  Option B (rack `.adg` + new nested-device param access, no reloads) = plan Task 6.
- Scratch: `serum2_test.als` has a `.bak`; failed `serum2_mcp.adv` + `serum_probe_rack.adg` +
  `serum2_mcp_probe.vstpreset` left in User Library (harmless).

## detect_key (PR #43) - SHIPPED v0.23.0 (2026-06-24)
SHIPPED: PR #43 squash-merged (0d12d85), tag v0.23.0 created (= main), marketplace `ableton`
ref v0.22.0 -> v0.23.0 (@5dc6c00) + build-readme. 148 tools. Live-verified + interactive MCP
tool confirmed after CC restart.

### Detail (was: LIVE-VERIFIED, pending ship)
Branch `feat/detect-key`. New tool `detect_key` (148 tools, v0.23.0 in-tree): KS-profile
key detection from MIDI notes, audio chroma (brew Python + librosa), or both combined
(`source` in {auto, midi, audio}; tap -> ok:false). Returns ranked candidates with confidence,
`matches_live` flag, MIDI/audio source contributions, and graceful degradation when librosa
is unavailable. Offline gate: 870 tests pass; server import + remote-script py_compile clean.
- LIVE-VERIFIED (Live 12.4 Suite, 2026-06-24): source=midi -> "C major" (0.93); source=auto same;
  source=audio on factory "Banjo Arpeggio E Minor" loop -> "E minor" (matches filename), analyzed:1;
  source=tap -> ok:false. matches_live True for C Major / False for D Major (live_scale.root_note
  returns INT - confirms the whole-branch-review fix that maps it through pitch names). Scratch
  clip + audio track cleaned up.
- NEXT: ship v0.23.0 (merge PR #43, gh release create v0.23.0, marketplace ableton ref bump + build-readme).

## Stem separation - LIVE-VERIFIED, pending ship (2026-06-22)
Branch `feat/stem-separation` (PR #42). New tool `separate_stems_to_arrangement` (147 tools):
separates a mixed audio file into stems (Demucs CLI), detects tempo + key (librosa via
`scripts/analyze_audio.py` under brew Python), sets project tempo + song scale, then lays each
stem on its own audio track at bar 1 of the Arrangement (warp OFF, full length, phase-locked).
Plus pure `stem_utils.py`, the analysis script, and the `/ableton:stems` command (with up-front
`fresh=true` confirmation).
- Stems are written under the User Library (`Samples/Stems/<model>/<name>`) so Live's browser
  indexes + loads them; resolved by polling `get_browser_items_at_path` on the specific folder
  (the `_carrier_uri` pattern - fast, no deep walk, no basename collision).
- Full-length placement: Live auto-warps a loaded sample (truncating the placed clip to the
  warp-derived beat count). `duplicate_clip_to_arrangement` gained `warp_off` + `clip_seconds`:
  it unwarps the PLACED arrangement clip (fresh) and sets `end_marker` to the sample's true
  seconds. KEY gotcha: do NOT pre-unwarp the session staging clip - that leaves it in a state
  the normalize can't extend (clip stays truncated). RS-side change (reinstall + Live relaunch).
- LIVE-VERIFIED on Live 12.4: 4 stems, clips end_time 41.0167 beats = full 20s @123.05, warp off,
  phase-locked at bar 1, session slots empty, tempo+key applied. 851 offline tests pass.
- NEXT (ship): bump pyproject + plugin.json to next version + `uv lock`, merge PR #42, gh release,
  bump marketplace `ableton` ref + `node scripts/build-readme.js`.

## Master tap (#31) - SHIPPED v0.21.0 (2026-06-22)
Branch `feat/master-tap` merged (PR #41, squash 92ece7b), tag v0.21.0, marketplace `ableton`
ref bumped v0.20.0->v0.21.0 (@06c08d8). 146 tools (deploy_taps gained a param, no new tool).
Closes the pre-fader blind spot: per-track MCP Taps are PRE-FADER (the tap is a device in the
chain; the mixer fader sits after it), so a fader move never changes a per-track reading and
there is no post-fader program-loudness reference. The only post-fader point is the master bus.
- **`deploy_taps(include_master=True)`** auto-adds a tap on the master bus in auto-target mode;
  `include_master=False` skips it, an explicit `track_indices` list with `-1` selects master.
- **`measure_mix` / `analyze_set(measure=True)`** partition the master tap out of cross-track
  findings (it would skew loudness_balance/masking) and surface it separately - `data.master` /
  `mix_signal.master`. New pure helper `masking_utils.partition_master(sigs)->(per_track,master)`.
- `_find_taps`/`_delete_device_raw`/`remove_taps` gained the master path (3-tuple
  `(track_type,track_index,device_index)`). No remote-script change (handler already accepts
  `track_type="master"` from PR #24).
- Pre-fader limitation documented on measure_mix/gain_stage_track/balance_mix docstrings +
  /ableton:analyze, /ableton:produce, and a design spec.
- **LIVE-VERIFIED Live 12.4** (blank set): deploy_taps auto-loaded a master tap that streamed
  (`index:-1 kind:"master"`), list_taps reported it, remove_taps deleted it (`track_type:"master"`),
  no errors. 834 offline tests. **DONE.** Open issues remaining: #36 groove-pool population.

## Arrangement automation (#30) - SHIPPED v0.20.0 (2026-06-22)
Branch `feat/arrangement-automation` merged (PR #40, squash 13b59c0), tag v0.20.0, marketplace
`ableton` ref bumped. New tool `set_arrangement_automation` (Composition, 146 tools) writes
Arrangement-timeline breakpoint envelopes via the `.als` probe backdoor.
**FULLY LIVE-VERIFIED on Live 12.4.2**: the full tool flow with `reload=True` returned
`reloaded:true`; the Transpose envelope (pointee 22411) round-trips on disk with unique
sequential FloatEvent Ids (22576-22580) + the -63072000 pre-roll sentinel + all 4 points.
**Critical bug found+fixed during build**: Live 12 rejects the set as corrupt unless every
`<FloatEvent>` has an `Id` (allocated from `<NextPointeeId>`); the builder omitted them -
offline well-formedness tests missed it. Also fixed `_reload_set` (answer the stop-audio
dialog with Return, not Cmd+D) + path fallback. 826 offline tests pass.
See [[issue30-arrangement-automation]] for full live findings.
- **Mechanism:** per lane, set the target param to a unique sentinel via the LOM, read back
  the stored value, `save_set`, then `find_target_after_manual(xml, value)` locates the single
  matching `<Manual>` -> next `<AutomationTarget Id>` = PointeeId. Inject `<AutomationEnvelope>`
  into the owning track's `<Envelopes>`, patch the probed `<Manual>` back to the first point,
  `write_als`, reload in place (Cmd-N + `open`, settle/retry the stale-song race). Quantized
  params unsupported in v1.
- **Path auto-resolve:** parse Live's `Log.txt` last `Loading document "<x>.als"` (handles /tmp +
  arbitrary dirs; sidesteps the iCloud stale-copy trap). `_current_set_path()` in server.py.
- Pure XML logic trimmed to probe-based targeting in `als_automation_utils.py` (deleted the
  name/ordinal navigator). Helpers `_reload_set`/`_arr_auto_impl` behind seams, unit-tested.
- **DONE.** Shipped as v0.20.0. Open issues remaining: #31 master tap, #36 groove-pool population.

## Save tools (#34) - v0.18.0, 144 tools (2026-06-21)
Save the Live set from the MCP (the LOM has NO save API - `Song` exposes no
file_path/save/is_modified). Driven through Live's File menu via System Events.
Branch `feat/save-tools` (base `main` @07e6a24). PR/release pending.
- **save_set(name=""):** empty name saves a TITLED set in place (File > Save Live Set;
  no-op if clean); an Untitled set requires a name; a non-empty name Saves-As.
- **save_set_as(name):** Save-As under a new name; reports a best-effort resolved `path`
  by searching common save folders (`_SAVE_SEARCH_ROOTS`).
- **Scope (deliberate):** the tools control the set NAME, not the directory. Ableton's
  Save-As panel saves to its LAST-USED location wrapped in a `<name> Project/` folder.
  Arbitrary-directory navigation is NOT exposed - the panel has no AX-pressable Save
  button, typing `/` hijacks Go-to-Folder (it once saved a garbage-named set), and the
  Go-to-Folder confirm is unreliable. Opening the panel uses a focus-independent File-menu
  click; the save itself needs Live frontmost for ~2-3s (keystroke confirm).
- **restart_live unchanged** (the Untitled save_path idea was dropped as unshippable).
- Pure logic in `save_utils.py` (`clean_set_name` rejects `/`+`:`, `is_untitled_title`).
- **LIVE-VERIFIED via the MCP tool on Live 12:** save_set_as("mcp_verify") -> saved + file
  on disk + path; save_set() in-place -> saved, no panel; save_set_as("bad/name") -> clean
  error. 782 offline tests pass.

## Clipping detection (#28) - SHIPPED v0.17.0, 142 tools (2026-06-21)
Flag any track/return/master peaking at/above 0 dBFS. PR #37 squash-merged (@08c3dfd), release v0.17.0
published, marketplace `ableton` ref bumped v0.16.0->v0.17.0 + pushed. Release chain verified
(local=origin=tag=08c3dfd). Issue #28 closed.
- **check_clipping(window_s, ceiling_db, include_returns):** peak-holds Live's post-fader output meters
  over a short playback pass (NO Max tap needed) -> per-entity {peak_dbfs, is_clipping, overshoot_db} +
  offenders worst-first. New Remote Script handler `get_output_meters` (instantaneous output_meter_left/right).
- **analyze_set:** new `health.no_clipping` Fail rule. `measure=True` derives clipping from per-track tap
  peaks when taps present, else runs the no-tap peak-hold pass; promotes out of deferred; pass finding when clean.
- **apply_findings:** `generate_actions` emits a deterministic fader-trim action (land peak ~-3 dBFS) for
  tracks/returns/master. Pure logic in new `clipping_utils.py` (peak_to_dbfs/annotate_meters/clipping_flags).
- **LIVE-VERIFIED on Live 12** (full loop): built an 808-kit scratch track + Utility boost -> check_clipping
  flagged track+Master at 0.0 dBFS; analyze_set(measure,health) -> 2 health.no_clipping fails w/ actions;
  apply_findings dry-run -> apply (applied_count 2); re-check -> any_clipping false (track -0.9, Master -1.6).
- **KEY LIMITATION (confirmed live):** Live's `output_meter_left/right` CLAMPS at 0 dBFS (1.0 linear), so the
  no-tap path reads `peak_dbfs` max 0.0 and `overshoot_db` always 0.0 on a hard over - it detects THAT a
  track clips but not HOW FAR. The auto-fix trims a fixed amount from the clamped reading (one pass cleared a
  small over in testing; a severe over may need a 2nd pass). The tap path (`true_peak_dbtp`) reports the real
  overshoot. Small follow-up: note the 0-dBFS clamp in the check_clipping docstring (not yet done).
- 749 offline tests pass.

## Groove Pool loading (#36) - v0.16.0, 141 tools (2026-06-21)
Branch `feat/groove-pool-loading` (base `main` @ed32446). Spec + plan under `docs/superpowers/`.
Follow-up to #27: there was no MCP path to ADD a groove to the Groove Pool (assignment only worked
on grooves already in it). SOLVED via the `.alc` clip-embed backdoor, spiked + PROVEN live on Live 12.4
(pool grew 1->2, groove assignable).
- **Mechanism:** a factory `.agr` `<Groove>` is injected into a device-less factory `.alc` wrapper's
  `<GroovePool><Grooves>`, the clip's `<GrooveSettings><GrooveId>` points at it; the carrier is written
  to `<UserLib>/Clips/`, loaded onto a scratch MIDI track via `load_browser_item` (Live MERGES the groove
  into the project pool), then the scratch track + temp `.alc` are deleted (groove persists). Live-11 `.agr`
  cosmetic nodes (`ScaleInformation`/`IsInKey`/`NoteSpellingPreference`/`PreferFlatRootNote`/`NoteEditorFold*`)
  are stripped so a Live-12 LiveSet accepts them.
- **Tools (2):** `load_groove_to_pool(name_or_path)` (skip-on-duplicate; returns pool name+index) and
  `search_grooves(query, limit, sources)` (discovery - factory `Core Library/Grooves` + User Library).
  Pure logic in new `groove_preset_utils.py` (unit-tested); NO Remote Script change.
- **REMOVAL is runtime-confirmed INFEASIBLE** (probed Live 12.4): `GroovePool.grooves` is a read-only
  `Vector` (`del grooves[i]` -> "Cannot modify read only container"); no `delete_groove`/`Groove.delete`.
  Handled by skip-on-duplicate + docs (manual right-click Remove is the only true removal). `Groove`
  feel params (timing/random/velocity/quantization/base/name) ARE settable -> a "neutralise to 0"
  soft-delete is possible (deferred, not v1).
- **Status:** Tasks 1-6 implemented + reviewed (all clean); docs/version bumped to v0.16.0 / 141 tools.
  729 offline tests pass. **LIVE-VERIFIED end-to-end on Live 12.4** (the actual server tool fns vs the
  running set): search_grooves loadable flags correct; load_groove_to_pool adds XML grooves (Rock Fatback,
  Disco, Cha-Cha-Cha, Jazz 50s), dup-skip works, binary `.agr` -> clean error, set left byte-identical
  (4 tracks -> 4 tracks), loaded groove ASSIGNABLE by index AND name.
- **Robustness fixes from live verification** (offline gates couldn't catch): (1) create/delete-track wire
  key is `index` not `track_index` (else deletes user track 0); (2) browser indexes a new carrier ~4.6s
  after write -> poll; (3) keep wrapper `<Devices>` intact (flat-regex emptying corrupts nested rack chains);
  (4) the carrier load APPENDS its own track -> delete the appended track(s) by count-delta (no scratch
  track); (5) strip Live-11 `<OriginalFileRef>` provenance + detect the proprietary BINARY `.agr` format
  (~half of factory grooves) -> clean error + `loadable` flag.
- **Coverage caveat:** ~116/219 factory grooves are plain-XML (loadable); 103 are a binary format the
  backdoor can't read (flagged `loadable:false`). All User-Library XML grooves load.
- **NEXT:** ship - PR, squash-merge, release v0.16.0, bump marketplace `ableton` ref + build-readme.

## Groove & swing (#27) - Phase 0 SPIKE VERDICT 2026-06-21
Branch `feat/groove-swing` (base `main` @6def31e). Spec/plan under `docs/superpowers/`.
- **Task 1** groove_utils pure swing math: DONE (6e5cf8a..310d659).
- **Task 2** `swing_clip` tool: DONE (4a59695), live-verified on Live 12.
- **Task 3** Phase 0 groove-assignment spike: **DONE - VERDICT: Python LOM assignment WORKS** (Live 12.4).
  - `clip.groove = song.groove_pool.grooves[i]` does NOT raise AND genuinely changes the clip's
    groove. Proven by a reversible A->B->A round-trip ("Swing 16ths 66" <-> "Swing 8ths 54"), each
    change confirmed on a SEPARATE read (same-task read-back lags per the song-property-write rule).
  - `clip.groove = None` RAISES `ArgumentError` (C++ sig `None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)`)
    -> cannot CLEAR a groove by assigning None; the setter is a real type-validated C++ binding (not a no-op
    stub), which is itself strong evidence the assignment is genuine. Clearing needs another path (TBD).
  - `clip.groove` / `clip.has_groove` READ fine. The Live 11 LOM doc marking `Clip.groove` get-only is
    INACCURATE for Live 12's embedded Python. **No Max device / no `.alc` backdoor needed for assignment.**
  - **Open sub-problem (sub-probe A, pool population):** grooves are NOT in the LOM `app.browser`
    categories (no "grooves" category) -> cannot load a factory `.agr` into the Groove Pool via MCP yet.
    Assignment works only on grooves ALREADY in the pool (user-dragged or template default). Pool
    population is a follow-up (Max path or browser-hotswap research).
  - Aside: this dev machine's Live 12 default template auto-applies "Swing 16ths 66" to every new clip
    (template-specific, not general).
  - **Phase 2 SHIPPED on this branch (d800b8b):** `assign_groove_to_clip` (by pool index or name) +
    `get_groove_pool`, pure-Python path. Replaced the temporary probe. RS handlers live-verified via raw
    socket on Live 12 (list/assign-by-index/assign-by-name OK; bad index/name -> clean errors).
    `normalize_groove_selector` unit-tested; MUTATING_COMMANDS synced; 712 tests pass.
  - **Task 4 docs DONE (7e2597c):** best-practices "Groove & swing" section, produce Stage-3 feel note,
    spec verdict, tool index/docs regenerated -> **139 tools / 20 categories**.
  - **SHIPPED v0.15.0 (2026-06-21):** merged via PR #35 (squash @9dbff4c), released v0.15.0,
    marketplace `ableton` ref bumped to v0.15.0 + pushed. MCP-level live check passed post-restart
    (get_groove_pool + assign_groove_to_clip by index/name; negatives clean). Issue #27 CLOSED.
    Follow-up #36 filed: Groove-Pool population (load `.agr` - grooves absent from the LOM browser;
    investigate Max LiveAPI / `.alc` backdoor).

## /ableton:produce command (#4b) - LIVE VERIFICATION DONE 2026-06-20
Branch `feat/produce-command` (base `main` @01a8af6). Spec + plan committed under
`docs/superpowers/`. Command authored (`commands/produce.md`); Tasks 1-2 done.
**Task 3 (live verification) COMPLETE** - drove all stages end-to-end against Live
12.4 building a House track (124 BPM, A minor, 6 tracks, 128 bars / 8 sections;
saved as `tester8.als`). Stages run: Foundation -> Parts -> Arrangement -> FX ->
Mix (metered) -> Master (limiter, ceiling ~-1 dB, True Peak mode).

**Findings (filed as issues on Project #29 "ableton-mcp-max Roadmap"):**
- #30 - no arrangement TIMELINE automation (FX/param envelopes bound to timeline
  position); feasible substitute = self-animating LFO devices + static sends.
- #31 - per-track MCP taps are PRE-FADER: `measure_mix`/`balance_mix`/
  `gain_stage_track` per-track LUFS reflect instrument level, NOT the fader. You
  cannot verify a fader balance by re-measuring per-track taps; true mix/loudness
  verification needs a MASTER tap (only post-fader point). `measure_loudness` +
  `analyze_set` master loudness already require a master tap (none auto-deployed).
- #32 - **shipped BUG (v0.12.0/v0.13.0): gain tools crash** `'<=' not supported
  between dict and float` - `get_mixer` returns `volume` as `{value,min,max}` but
  `adjust_track_gain`/`gain_stage_track`/`balance_mix` fed it to
  `live_volume_to_db`. **FIXED** @6067365 (`_vol_value` coercion + regression
  test; old test fakes returned a bare float, masking it). 699 -> 700 tests.
- #27 groove/swing playback automation, #28 clipping/peak detection in
  analyze_set, #29 set_song_scale/set_key (filed in the prior session).
- Command-doc gaps (candidate edits to `commands/produce.md`, NOT yet applied):
  Stage-2 Foundation auto-fire is silent (no notes yet -> summarize, don't fire);
  sampled "chord/stab" presets trigger whole chords per note (bad for mono leads
  -> note); Session-vs-Arrangement view (say "press Tab" at Arrangement
  checkpoint); the command has NO FX/automation stage (FX was an ad-hoc step);
  `get_track_info` has no `track_type` (returns/master need get_mixer/get_device_info).

**Remaining:** apply the command-doc fixes above (judgment); Task 4 = ship the
produce command + the #32 fix together (v0.13.0 -> v0.14.0: bump
pyproject/plugin.json + `uv lock`, release, marketplace `ableton` ref bump).

## Closed-loop remediation (roadmap #3) - SHIPPED 2026-06-19 as v0.12.0
Spec: `docs/superpowers/specs/2026-06-18-closed-loop-remediation-design.md`
Plan: `docs/superpowers/plans/2026-06-18-closed-loop-remediation.md`
4 new tools (128 -> 132), new "Remediation" category (19 total), no RS changes, 656 tests, version 0.12.0:
- **`adjust_track_gain`**: shift a track fader by delta_db (no playback; uses live_volume_to_db inverse)
- **`gain_stage_track`**: play + measure LUFS via tap + iterative convergence to target_db
- **`balance_mix`**: single coherent measure_mix pass + per-tap-kind level corrections
- **`apply_findings`**: translate analyze_set findings (with new `action` field) into a correction plan; dry_run=True default
- **Finding enhancement**: `action` dict added to fixable findings from analyze_set (deterministic fixes only; judgment-required findings stay text-only)
- **New module**: `remediation_utils.py` (db_to_live_volume inverse, generate_actions, build_correction_plan, compute_balance_deltas)
- **Tests**: 38 new unit tests (test_remediation_utils.py + 4 new tool test files), 618 -> 656 passing
- **SHIPPED v0.13.0 (2026-06-19): sample sourcing** - PR #26 squash-merged (@6b85ebc), release v0.13.0 published, marketplace ableton ref bumped v0.12.0->v0.13.0 + pushed (@af7f30b). 136 tools, 699 tests, 20 categories. NEXT = sub-project #4b (/ableton:produce skill).

## Arrangement intelligence: section map read/write (2026-06-18)
Roadmap item #2 of the "autonomous track production + closed analyze->act loop"
initiative. Adds 2 new tools (126 -> 128, new "Arrangement structure" area):

- **`get_arrangement_structure`**: derives section spans from cue points
  (primary) or clip change-point inference (fallback). Returns per-section facts:
  active tracks, clip count, coverage, and min-max normalized energy.
- **`build_arrangement`**: places Session clips onto the Arrangement timeline
  from an explicit section map (name + length_bars + clips list), tiles clips
  via `repeat: "fill"` or integer count, and optionally writes named cue
  locators so the structure round-trips through `get_arrangement_structure`.

New module `arrangement_structure_utils.py` holds all bar/beat math, inference,
and tiling logic (no Live dependency, fully unit-tested). No new Remote Script
commands - both tools compose existing `get_transport` / `get_cue_points` /
`get_arrangement_clips` / `duplicate_clip_to_arrangement` / `create_cue_point`
calls. Offline test suite: 566 -> 618 passed. Version: 0.10.0 -> 0.11.0.
Released as v0.11.0; marketplace ref bumped.

**LIVE-VERIFIED 2026-06-18 vs Live 12.4 Suite (4/4, 120 BPM):**
- `build_arrangement` 3-section map (Intro 4 / Main 8 / Outro 4 bars), 2 scratch
  MIDI tracks, `repeat: "fill"`, `write_locators: true` -> 28 clips placed (4+4 /
  8+8 / 4), 3 locators written ✓
- `get_arrangement_structure` read-back: `source: "cues"`, 3 sections, correct
  start_bar/length_bars, active_tracks/energy ordering ✓. Locators receive Live
  auto-sequential names ("1"/"2"/"3"), not section names (LOM read-only - doc
  reflects this) ✓
- `replace: true` re-build: 28 clips after (no duplicates, existing cleared) ✓
- Delete all locators -> `get_arrangement_structure` falls to `source: "inferred"`;
  16 "Section N" sections (1-bar change-points from uniform 1-bar clips), density
  labels present, energy ordering correct ✓
- Negative cases: empty name, negative length_bars, empty slot - all clean errors
  with no mutation ✓
- Self-cleaned: scratch tracks + locators deleted, set back to baseline 4 tracks ✓

## SHIPPED v0.10.0 (2026-06-16): master/return device access + composition layer
PR #25 (composition layer) squash-merged to `main` (@2537e7a); master/return access (#24, @9afd32f) was
already on main from the prior session. Version bumped 0.9.0 -> 0.10.0 across pyproject/plugin.json/uv.lock
(@6e52e3b); `gh release create v0.10.0` (tag @6e52e3b); marketplace `ableton` ref bumped v0.9.0 -> v0.10.0 +
README rebuilt + pushed (@ede39e9 in robworks-claude-code-plugins). Full chain verified: local main =
origin/main = ls-remote tag commit; remote marketplace ref = v0.10.0. **Tool count 118 -> 126.** Both feature
areas live-verified vs Live 12.4 (master/return params + load; composition all 8 tools incl. get_song_scale
auto-read). **Nothing functional queued** after this - the 5-part "autonomous track production" roadmap has #0
(master/return) + #1 (composition) shipped; #2 arrangement intelligence, #3 closed-loop remediation, #4
/ableton:produce skill remain as future specs.

## Composition layer: MIDI generators + clip transformers (2026-06-16)
Sub-project #1 of the "autonomous track production + closed analyze->act loop" initiative. Adds
server-side MIDI-composition primitives that emit notes through the existing note path
(`create_clip`/`add_notes_to_clip`/`replace_clip_notes`). Branch `feat/composition-layer`. **8 new tools
(118 -> 126, new "Composition" category, 17 total).**
- **Pure module `ableton_mcp_max/composition_utils.py`** holds the whole music model + note math (no Live
  dependency, server-side only): key parsing (sharps/flats), 14-scale interval table + aliases,
  `resolve_key_scale` (explicit params win, else read the set, else fall back to C natural minor),
  `scale_pitches`/`degree_to_pitch`/`snap_to_scale`; a chord model (roman numerals resolved DIATONICALLY by
  stacking scale thirds via `degree_to_pitch` - quality emerges from the scale - plus absolute chord symbols
  like `Cmaj7`/`Am7`); 4 generators (`build_chord_progression`, `build_bassline`, `build_melody`,
  `build_drum_pattern`) and 4 transformers (`humanize`, `quantize_to_scale`, `arpeggiate`, `harmonize`). All
  randomness is seedable via `make_rng(seed)` (same seed+params -> identical notes). Octave convention =
  Ableton labels (`pitch = pc + 12*(octave+2)`, so octave 3 -> C3 = 60).
- **4 generator tools** (`generate_chord_progression`/`generate_bassline`/`generate_melody`/
  `generate_drum_pattern`) write into a session slot: create the MIDI clip if empty (length = bars*4 beats,
  4/4), else require `replace=true`; `key`/`scale` optional (read the set when omitted). **4 transformer
  tools** (`humanize_clip`/`quantize_clip_to_scale`/`arpeggiate_clip`/`harmonize_clip`) read a clip's notes,
  transform, write back via `replace_clip_notes`. All use `clip_index` (house style).
- **Remote Script:** one new read command `get_song_scale` -> `{scale_name, root_note, scale_intervals}`
  (inline read off `self._song`, Py2/3.7-safe, try/except-guarded; degrades to defaults on older Live).
  Powers the auto-read-the-set's-key path. `scale_intervals` is the LOM's own list (e.g. Major ->
  [0,2,4,5,7,9,11]), so custom set scales work too. Feasibility confirmed against the Live 11/12 LOM doc
  (scale_name/root_note read/write, scale_intervals read).
- **Tests:** 48 new offline composition tests (scales/chords/generators/transformers), full suite **566
  passed**; server imports clean; RS py_compile clean. Built subagent-driven (spec + quality review each
  task; reviews caught + fixed: walking-bassline fractional-segment bug, durations-length validation,
  arpeggiate single-note re-trigger footgun, clip_slot_index->clip_index API consistency).
- **LIVE-VERIFIED 2026-06-16 vs Live 12 Suite** (working-tree server.py driven directly against the live
  9877 socket, bypassing MCP, on a self-cleaning scratch MIDI track): all 8 tools pass. chords -> 12 notes,
  pitch-classes exactly {0,2,4,5,7,9,11} (clean C major); bassline 4 roots; melody 11 (seed=42); drums 28
  with kicks at beats 0-7 (four_on_floor x2 bars); humanize/quantize 11 each; arpeggiate expanded the 12-note
  chord clip to 64; harmonize 4->8; occupied-slot guard correctly errors without replace and succeeds with
  replace=true; scratch track deleted -> track_count restored. The `_emit_to_slot` empty-slot probe logs
  "No clip in slot" by design (try/except treats it as empty -> create).
- **DEFERRED PATH NOW VERIFIED (2026-06-16, vs Live 12.4 after a Live bounce loaded the new RS):** the
  `get_song_scale` auto-read (generators with NO key/scale). Pre-bounce, the running Live still had the OLD
  RS, so `get_song_scale` over 9877 returned "Unknown command" and generators fell back to C natural minor
  (confirming the fallback). After `restart_live(discard)` loaded the new RS, `get_song_scale` returned
  `{scale_name:"Major", root_note:0, scale_intervals:[0,2,4,5,7,9,11]}` (the default set's actual C-major
  scale), and `generate_chord_progression(["I","IV","V","I"])` with no key/scale produced unambiguous MAJOR
  triads (I=C-E-G 60/64/67, IV=F-A-C, V=G-B-D - E natural 64, NOT the fallback Eb 63). Scratch track
  deleted -> 4 tracks restored. **Composition layer is now FULLY live-verified.** **NOT yet released** -
  per plan, one release will bundle #0 + gap C + #1.
- Specs/plans: `docs/superpowers/specs/2026-06-16-composition-layer-design.md`,
  `docs/superpowers/plans/2026-06-16-composition-layer.md`. NEXT = release (PR feat/composition-layer ->
  main, bundle the unreleased master/return #24 already on main + composition layer as v0.10.0).

## Master/return device access: params + effect loading (2026-06-16)
First sub-projects of the new "autonomous track production + closed analyze->act loop" initiative
(5-part roadmap: #0 master/return access, #1 composition layer, #2 arrangement intelligence, #3 closed-loop
remediation, #4 /ableton:produce skill). Branch `feat/master-return-device-params`. Closes the major gap that
the master/return chain was unreachable for device-parameter read/write AND device loading.
- **Gap #0 - device parameters on return/master:** `get_device_parameters` + `set_device_parameter` gained
  `track_type='regular'|'return'|'master'` (server forwards it incl. the name->index pre-fetch in
  set_device_parameter; Remote Script handlers now use the existing `_resolve_device(track_index, device_index,
  track_type)` helper instead of hardcoding `self._song.tracks[track_index]`). Backward-compatible (default
  regular). Same pattern as the sibling `track_type` tools (get_device_info/set_device_on/set_chain_property).
- **Gap C - load effects onto return/master:** `load_instrument_or_effect` + `load_preset` gained `track_type`
  (both route through the one `load_browser_item` command -> `_load_browser_item`, which now resolves the target
  via `_resolve_track` and selects it before `app.browser.load_item`). `load_drum_kit` left regular-only
  (instruments can't host on audio-only return/master). No instrument-vs-effect guard (documented, not guarded).
  FEASIBILITY CONFIRMED LIVE: `load_item` honors a master/return selection - NO holder-track+copy workaround
  needed (supersedes the old "master/return can't host loaded devices" note).
- **Offline:** +6 tests (test_device_params_track_type.py x3, test_load_track_type.py x3), full suite 518 passed,
  py_compile clean, server imports. Subagent-driven (spec+quality reviewed each task). Docs regenerated, tool
  count UNCHANGED at 118 (arg-only changes, no new tools).
- **LIVE-VERIFIED 2026-06-16 vs Live 12.4 (working-tree server via AbletonDev):** Return A Reverb param
  read+write(Decay Time 0.443->0.75)+separate-read-back+restore; Master EQ Eight read(84 params)+write(`1 Gain A`
  0->6)+restore; loaded EQ Eight onto Master (idx 0) AND Return A (idx 1, appended after Reverb) via track_type;
  regular-track load still works with no track_type; all scratch devices deleted (master->0, returnA->1 Reverb,
  regular->0). RS reinstalled + Live bounced via restart_live twice during the cycle.
- **Out of scope (later specs):** master/return automation envelopes (B). Specs/plans:
  `docs/superpowers/specs/2026-06-16-master-return-device-params-design.md` (+ `-load-devices-onto-master-return-design.md`),
  matching plans under `docs/superpowers/plans/`. NEXT = finish branch (PR) -> release; then sub-project #1 (composition layer).

## Adapt factory-asset reads to the RUNNING Live version (2026-06-15)
Closes the one spot that ignored which Live the user runs: on a machine with BOTH 11 and 12 installed,
factory-asset reads (preset patching, the wavetable table list, factory racks) always took the
alphabetically-first bundle (Live 11). Now the server asks Live its version and reads the matching bundle.
- **Remote Script:** new `get_application_version` read command → `{major,minor,bugfix}` via
  `self.application().get_*_version()`. Inline read (no main-thread schedule).
- **server.py:** `_running_live_major()` (queries the RS) + `_core_for_major(major)` (globs the matching
  bundle) + `_app_core()` (running bundle's Core Library, else the `_APP_CORE` multi-version glob fallback).
  All `_APP_CORE` asset-read sites now call `_app_core()`. Not cached → stays correct if Live versions
  switch mid-session. Single-version installs are unaffected (glob already found the only bundle).
- **Verified LIVE on Live 12.4.2:** `get_application_version` → `{major:12,minor:4,bugfix:2}`; running the
  working-tree server against the live socket, `_app_core()` resolved the **Live 12** Core Library and
  `_factory_default_adv("Wavetable.adv")` sourced from the Live 12 bundle (was Live 11 pre-change). Live-11
  path is the same code with major=11 (offline-tested; `_core_for_major` glob matches "Ableton Live 11 Suite").
- Offline: +5 tests (`test_app_core.py`), full suite 503 passed. RS stays py_compile-clean / 3.7-safe.
- **Graceful Live quit (resolved):** `kill -TERM` is a signal, not a quit — Live flags a crash and shows a
  "recover your work?" modal on relaunch that blocks control-surface init (9877 never binds). Quit via the
  real path instead: Apple `quit` event + (if the save dialog appears) ACTIVATE Live then answer by keystroke.
  **⌘D = Don't Save** (Ableton's custom AXDialog IGNORES ⌘⌫; verified live), **Return = Save**. Now shipped
  as the `restart_live` tool + `/ableton:restart` command below.

## Automated Live restart: restart_live tool + /ableton:restart command (2026-06-15)
Lets the agent bounce Ableton end-to-end (quit → relaunch → wait for the surface) with no crash-recovery
prompt, prompting the user before discarding unsaved work. Motivated by automating the Remote-Script
reinstall+restart loop.
- **server.py:** `restart_live(save="discard"|"save", relaunch, wait_timeout)` MCP tool over
  `_restart_live_impl` + OS seams (`_live_app_and_pid` via the 9877 listener PID, `_osa`/`_osa_async`,
  `_pid_alive`, `_open_app`, `_port_listening`, `_wait_until`). Flow: fire Apple `quit` (async, since it
  blocks on the dialog) → "still alive after ~5s" = dirty → ACTIVATE Live + answer (⌘D discard / Return save)
  → wait for exit → relaunch → wait for 9877. No LOM save-state/save API exists, hence the alive-after-quit
  dirty heuristic and keystroke save.
- **command `commands/restart.md` (`/ableton:restart`):** asks Save/Don't-Save/Cancel UP FRONT
  (AskUserQuestion), then calls the tool with that policy — so prompting works (the MCP server itself can't
  elicit). Reports `was_dirty`/`quit`/`surface_up`, handles the Untitled+save case, and reminds that a
  server.py change still needs a Claude Code restart (only Ableton is bounced).
- **HARD-WON GOTCHAS:** (1) System Events keystrokes go to the FRONTMOST app → must `activate` Live before
  answering, or ⌘D lands on the terminal. (2) Ableton's save dialog is a custom AXDialog with NO button
  titles and it IGNORES ⌘⌫ — **⌘D** is Don't Save (found by probing the live dialog). (3) `save` on an
  Untitled set opens a Save-As path dialog we can't fill → reported `quit:false` (name the set first).
- **VERIFIED LIVE on Live 12.4** via the working-tree code against the live socket: dirtied the set
  (set_tempo) → `restart_live(discard)` → `{was_dirty:true, dialog_answered:discard, quit:true,
  relaunched:true, surface_up:true}`, new Live on 9877, no recovery prompt.
- Offline: +9 tests (`test_restart_live.py`), full suite 512 passed. New tool filed in both doc-gen group
  maps ("Host lifecycle" / "Host Lifecycle"); docs regenerated (118 tools, 16 categories; `docs/index.md`
  hero counts bumped 117→118 / 15→16 + Target → "Live 11 & 12").

## Live 12 compatibility (2026-06-15, in progress)
Plugin was built for Live 11; auditing for Live 12 (both Suite installed on the dev machine).
**Static audit + safe code fixes DONE:**
- `scripts/install_remote_script.sh` rewritten to install into EVERY installed `Ableton*Live*.app`
  (Live 11 + 12), with a `LIVE_APP=...` override to target one. Backups namespaced per-app. The old
  script hardcoded the Live 11 path = the one hard blocker on a 12-only machine.
- Live 12 Remote Script INSTALLED (owner ryanrobson:admin, not root). `_Framework/ControlSurface.pyc`
  confirmed present in the Live 12 bundle (59 .pyc, same as 11) → the legacy control-surface base class
  still exists, so the script will load. **It appears in Live's Control Surface dropdown only because the
  `AbletonMCP` folder lives in `<app>/Contents/App-Resources/MIDI Remote Scripts/` — Live scans that dir
  at launch.** Live 12 never had the folder until this install.
- De-hardcoded the "Live 11" strings: `plugin.json` description ("11 and 12"), server.py factory-preset
  error message. `_factory_default_adv` already globs `Ableton*Live*.app` (version-agnostic); the
  factory `Core Library/Defaults/<cat>/` layout is identical in 11 and 12. User Library resolution
  already globs `Live */Library.cfg` (newest wins).
- **PORT 9877 IS SINGLE-OCCUPANT:** Live 11 + Live 12 can't both hold the surface at once. Quit Live 11
  before live-testing Live 12, or they fight over the socket.
- Preset XML schema bumped 11→12 (`MinorVersion 11.0_11300` → `12.0_12402`, root `MajorVersion=5`
  unchanged). `_factory_default_adv` `hits[0]` currently picks the Live-11 preset alphabetically =
  the SAFER cross-version choice (Live upgrades older schemas on load; may reject newer in older Live).

**LIVE-VERIFY ON LIVE 12 — ALL 5 PASSED (2026-06-15, vs Live 12.4 Suite; Live 11 quit, surface selected):**
1. ✅ Connect + dispatch — `get_session_info` returned 4 tracks/2 returns/master; 9877 bound by Live 12's
   surface. Confirms the `_Framework`-based Remote Script loads + dispatches in Live 12.
2. ✅ Preset-patch round-trip — `create_wavetable_preset` WROTE a valid preset (first load deferred only by
   the normal browser-index lag, same as Live 11). Plus offline: `build_wavetable_adv` +
   `detect_rack_type`/`summarize_rack_adg` run cleanly against the ACTUAL Live-12 factory `.adv/.adg`
   (the live tool reads Live 11's copy here since both bundles are installed and `hits[0]` is alphabetical).
3. ✅ Enums/structure — wavetable legend (146 tables) + unison map resolve. **Live 12 racks expose 16
   macros (was 8 in 11); `_check_macro_number` already allows 1..16 and `summarize_rack_adg` read all 16
   — no cap to fix.**
4. ✅ M4L tap — `MCP Tap.amxd` (built in Live 11 Max 8.5) loads in Live 12's Max 8.6, connects to the
   registry on 9878, streams (block_count climbing, 48 kHz); `read_track_meter` integrates end-to-end
   (nulls/peak 0 on a silent track, as expected). `remove_taps` cleared it.
5. ✅ Browser paths — `user_library/Presets/Audio Effects/Max Audio Effect` resolves; `MCP Tap` device visible.

**ONE FINDING (UX, not a break) — FIXED.** `deploy_taps` on Live 12 returned a FALSE-NEGATIVE
("Communication error: No data received" → manual-fallback message) because the M4L+Node boot in Live 12's
Max 8.6 is slower than the socket timeout — but the device DID load and stream (verified via
`get_track_info` + `get_audio_tap_status`). **FIX (server.py): on a load whose reply was lost (timeout
signature `_is_load_timeout`), deploy_taps now polls the tap registry (`_confirm_tap_via_registry`, 6×0.5s)
for a NEWLY-connected tap on that track and records it as deployed `{"confirmed_via":"registry"}` instead
of failing.** A pre-load uuid snapshot prevents false-confirming a pre-existing tap; clean "not in browser"
errors still fail fast (no poll). Offline-tested (+4 tests in test_taps_tools.py, suite 498 passed).
**LIVE-VERIFIED 2026-06-15 on Live 12 (cold Max boot):** with the cached plugin server disabled so the
working-tree server owned 9878, a cold `deploy_taps([0])` via AbletonDev returned
`deployed:[{track_index:0, confirmed_via:"registry"}]`, `failed:[]` — the timeout was rescued by the
registry poll exactly as designed (tap streaming, block_count climbing; removed after).

**PER-TRACK SIGNAL TAPS via a general bridge - SHIPPED as v0.8.0 (2026-06-15).** PR #20 squash-merged to
`main` (@9b85c0c); `gh release create v0.8.0`; marketplace `ableton` ref bumped v0.7.0 -> v0.8.0 + README
rebuilt + pushed (@15c0981 in robworks-claude-code-plugins). Live-verified end-to-end (see the Phase 5 entry).
Replaces the v0.7.0 master tap with a self-identifying M4L device family reporting to a Python-hosted TCP
**registry** (one socket, port 9878; devices are CLIENTS that announce identity + stream stats). Shipped as
**v0.8.0 (BREAKING device change)**. Spec `docs/superpowers/specs/2026-06-13-per-track-signal-taps-bridge-design.md`,
plan `docs/superpowers/plans/2026-06-13-per-track-signal-taps-bridge.md`. Subagent-driven (spec+quality review each task).
- **PHASE 1 (bridge + levels device) COMPLETE + LIVE-VERIFIED 2026-06-14.** Offline **454 passed**. Commits:
  `tap_registry.py` (`parse_frames` + thread-safe `TapState` ring buffers + `TapRegistry` TCP server w/
  testable `feed()` seam + disconnect eviction); server.py hosts `_tap_registry` on 9878, `_uuid_for_index`,
  reimplemented `get_audio_tap_status`/`reset_meter`/`read_meter` + new `list_taps`/`read_track_meter` +
  registry-backed `measure_loudness` (playback behind `_run_measure_playback` seam); device
  `m4l/MCP Tap.amxd` + `registry-client.js` + `MCP Tap.maxpat` (@7a69dd2).
- **SPIKE 0.2 (device self-id) PASSED.** Live-verified: device on track "3-Audio" reported `index:2 kind:regular`;
  moved to Master reported `index:-1 kind:master`. read_track_meter(-1) with a live Analog chord returned
  integrated **-17.0 LUFS**, momentary -13.3, short-term -15.8, true-peak -5.4 dBTP (peak 0.538, self-consistent).
  Silence -> nulls + peak 0, blocks still streaming. **The client-inversion (device->registry) + block streaming
  + server tools all proven end to end.**
- **M4L SELF-ID RECIPE (hard-won, 6 device iterations):** `live.path this_device` ONLY emits the device `id`
  (no path output on ANY outlet - confirmed by latch+resend diagnostic). Resolve the track instead via
  `live.object` `get canonical_parent` -> track LOM id, then `live.object`(`live_set`) `get tracks`/
  `get return_tracks`/`get master_track` -> find the track id's POSITION in those lists = (index, kind).
  Use `live.thisdevice` (NOT `loadbang`) to trigger, and a `metro` (NOT one-shot) so the identity re-sends
  past the ~1-2s Node-for-Max boot (a one-shot message is dropped: "Node script not ready"). Diagnostic
  channel = stuff raw tokens into an identity `debug` field surfaced by `list_taps`.
- **KNOWN PHASE-1 GAP:** the device sends no RMS (grafted v0.7.0 chain has no RMS tap) -> read_track_meter
  `rms`/`crest` are null; `bands`/`mid`/`side` are zeroed. RMS + 8-band spectrum + stereo land in the Phase 2/3
  DSP rework (the `block` frame already reserves the slots).
- **PHASE 2/3/4 PURE-PYTHON CORE COMPLETE + offline-tested (2026-06-14, offline 480 passed).** Built
  subagent-driven (spec+quality review each): `spectrum_utils.py` (`integrate_bands` + `band_profile_db`
  power-dB profile + `stereo_metrics` width/correlation); `masking_utils.py` (`masking_score` cosine overlap,
  `loudness_balance`, `headroom_flags`, `stereo_flags`); `measure_mix` MCP tool (reset-all-buffers ->
  `_run_measure_playback` seam -> read -> per-track signal via extended `_integrate_buffer` [now also emits
  bands/width/correlation] -> cross-track findings). `read_track_meter` additively gained bands/width/correlation.
  Reset-first ordering bug caught + fixed in review (measure_mix must reset before the capture window, else it
  integrates stale history; regression test `test_measure_mix_resets_stale_buffer_before_capture`).
- **PHASE 4.3 - DONE (Python core, offline 489 passed, @43266eb 2026-06-14; LIVE-VERIFY of measure=True
    PENDING with Phase 5).** Decision RESOLVED (user picked "opt-in flag"): the 4 cross-track checks surface
    as a separate analyze_set `mix_signal` section, NOT forced through the `evaluate_rules` predicate engine.
    Added 4 rules to `mixing.json` (`mixing.spectral_masking`/`loudness_balance`/`headroom_per_track`/
    `stereo_correlation`) - all `mode:deferred` + `signal_required:true` + `signal_kind:mix`, thresholds in
    a `params` dict, rationale/remediation/source (4 new anchors in sources.md). Pure helpers in
    `masking_utils.py`: `build_mix_findings(sigs, rules)` (maps rule id -> cross-track fn, reads params,
    status pass/severity) + `enrich_names(sigs, name_by_index)` (backfills blank device names from the LOM
    index). `analyze_set` gained `measure: bool = False` + `measure_window_s`: when True AND taps connected it
    runs a shared `_measure_pass` (plays the set via the `_run_measure_playback` seam), emits `mix_signal`
    {window_s, tracks, findings}, and PROMOTES the 4 ids out of `deferred_rules` (summary tally kept in step).
    **Default measure=False stays READ-ONLY** (no playback) - that was the user's chosen contract. `measure_mix`
    refactored onto `_measure_pass`; both enrich names via `_track_name_map()` (best-effort get_analysis_snapshot
    index->name, master=-1). `registry-client.js` inbound `{"command":"reset"}` handler already present.
    Code review (feature-dev:code-reviewer) found + FIXED a stale `summary.deferred` count after promotion; all
    other paths verified clean (no double-defer, params/kwargs aligned, read-only default holds, mutation mirror
    correct). NEXT live check: drop taps on 2+ tracks, `analyze_set(measure=True)` -> mix_signal with real
    findings + readable names + the 4 rules promoted out of deferred.
  - **Phase 2/3 DEVICE DSP - DONE + LIVE-VERIFIED 2026-06-14 (@0aa8797).** Added to `MCP Tap.amxd`: wideband
    RMS + mid/side (square->average~4800->snapshot~), and an 8-band spectrum via **`fffb~ 8 40 2.4 3.`** (fast
    fixed filter bank fed from the mono mid signal) -> square/average/snapshot per band -> pak slots 5-12.
    Pak expanded to 14 floats (block ms_l ms_r peak rms b0..b7 mid side); registry-client already mapped all 14.
    **LIVE measure_mix verified:** master chord -> bands peak in low_mid (band 2), width 0/correlation 1 (centered);
    two overlapping low-register chords on tracks 0+1 -> per-track signals + **masking score 0.986** (correctly high).
    rms/crest now populate (master crest ~20, per-track ~28). Stage built in 2 grafts (RMS+stereo, then fffb~).
    KNOWN: device reports empty track `name` -> measure_mix findings show `a:""/b:""`; Phase 4.3 must ENRICH
    names from the track index via the LOM for readable reports.
  - **PHASE 5 + LIVE-VERIFY - COMPLETE 2026-06-15 (offline 494 passed). RELEASE PENDING.**
    `deploy_taps`/`remove_taps` shipped (server.py): deploy browser-loads the User-Library `MCP Tap` onto
    every audio/instrument track (or explicit indices) with a manual-drag fallback if not indexed; remove
    deletes every `MCP Tap` by name (highest device index first). Seams
    `_audio_instrument_track_indices`/`_load_tap_on_track`/`_find_taps`/`_delete_device_raw` are stubbable.
    **LIVE-VERIFIED end-to-end vs Live 11.3.43:** deploy_taps auto-loaded all 4 tracks (no fallback),
    devices resolved index 0/1/2/3 + streamed, `analyze_set(measure=True)` returned real `mix_signal`
    (1-Analog -16.9 LUFS / 2-Analog -16.7, **spectral_masking 0.991** between them), all 4 mixing rules
    promoted out of deferred, summary.deferred=0, names enriched; remove_taps cleared all 4.
    **THREE bugs found + fixed during live-verify:** (1) `TAP_BROWSER_PATH` was a wrong guess
    `max_for_live/Max Audio Effect` (lists only the stock template) -> corrected to
    `user_library/Presets/Audio Effects/Max Audio Effect`. (2) `_measure_pass` sent the device a `reset`
    command that halted the patch's block stream (tap is a dumb relay, no device-side state) -> removed the
    device-reset loop; resets only the server-side buffer now (matches `measure_loudness`). (3) the `.amxd`
    was UNFROZEN -> when browser-loaded from the User Library it connected Node but couldn't resolve
    `registry-client.js`+deps, so the patcher loaded only partially (identity -99, no blocks). **Froze the
    device in Max -> self-contained 37108-byte `.amxd`.** Install docs corrected: DRAG the `.amxd` into
    Live's browser to register it in the content DB (a plain file-copy is NOT indexed); freeze before ship.
    See memory `m4l-tap-packaging-gotchas`. Docs done:
    tool count **112 -> 117** (15 categories unchanged), `commands/tool-index.md` + `docs/tools/**`
    regenerated, 5 hardcoded `docs/index.md` counts bumped, README + `m4l/README.md` updated (registry
    model, deploy_taps, completed DSP, v0.7.0 migration note), `/ableton:analyze` skill now offers the
    opt-in measure pass + Mix signal report section. **RELEASE (Task 5.4) REMAINING:** commit the
    live-verify fixes (server.py, m4l/MCP Tap.amxd, m4l/README.md, README.md, PROGRESS.md), then PR +
    v0.8.0 (BREAKING device change; bump pyproject/plugin.json + `uv lock`, `gh release create v0.8.0`,
    marketplace `ableton` ref bump + `node scripts/build-readme.js` - confirm latest shipped tag first via
    `gh release list`).
  - Deferred test nits: masking_utils `or True` tautology + boundary/precedence tests; `_uuid_for_index` could
    return the track dict; measure_mix `crest` uses last-block rms; findings carry `name` not `index`.

---

**M4L AUDIO TAP - SHIPPED in v0.7.0 (2026-06-13).** PR #19 squash-merged to `main` (@67b1d1d) -> version
bump @7b04b67; `gh release create v0.7.0`; marketplace `ableton` ref bumped v0.6.0 -> v0.7.0 + README
rebuilt + pushed @87d4cac in robworks-claude-code-plugins. Tool count 108 -> 112 (new "Metering" category).
COMPLETE + LIVE-VERIFIED end-to-end.
The `MCP Audio Tap.amxd` device (BS.1770 K-weighted loudness + sample-peak true-peak) is built and
**cross-validated live against iZotope Ozone 12**: our integrated/momentary LUFS tracked Ozone's input
loudness within <1 LU (e.g. momentary -10.6/-11.8 vs Ozone -11.0 LUFS), and our true-peak matched Ozone's
peak within ~0.1-0.3 dB (-4.1 = -4.1; -2.3 vs -2.4). Audio -> real LUFS; silence -> null. **The .amxd was
built by grafting the K-weighting/true-peak chain onto a known-good device wrapper via a Python script
(`ampf`/`meta`/`ptch` chunk format; keep the template plugin~/plugout~ + M4L wrapper, swap boxes/lines) -
NO hand-wiring; the device is dragged onto the Master from Finder.** Gotchas hit live: Max has NO `max`
object (use `expr max($f1,$f2)`); two loaded tap devices collide on port 9878 (EADDRINUSE) - keep exactly
one; pasting a .maxpat into the device editor is fragile, the script-built .amxd is the reliable path.

**M4L AUDIO TAP - Python side COMPLETE + offline-verified (branch
`feat/m4l-audio-tap`, 2026-06-12).** Closes the field-wide gap: the LOM exposes no audio signal, so
`analyze_set` deferred all loudness/true-peak rules. A Max-for-Live device on the Master meters the bus and
serves metering over a SECOND socket (`localhost:9878`, decoupled from the 9877 Remote Script). Tool count
108 -> **112** (new category "Metering (Audio Tap)"). Spec
`docs/superpowers/specs/2026-06-12-m4l-audio-tap-design.md`, plan
`docs/superpowers/plans/2026-06-12-m4l-audio-tap.md`. Built via subagent-driven TDD (Tasks 1-4 each
spec+quality reviewed; reviews caught bad gate-test vectors, missing retry-path tests).
- **Tasks 1-4 (Python) DONE + offline 427 passed.** (1) `loudness_utils.py` - pure BS.1770 gating/integration
  (absolute -70 LUFS + relative -10 LU gates, momentary/short-term windows, dBTP), stdlib-only, pytest-tested.
  (2) `tap_connection.py` - `AudioTapConnection` (9878 TCP, `{ok,data}`, reconnect-retry, graceful tap-absent).
  (3) 4 MCP tools: `get_audio_tap_status`/`reset_meter`/`read_meter`/`measure_loudness` (free-running meter +
  measure-loudness playback-pass wrapper). (4) `evaluate_rules` now EVALUATES a `signal_required` rule when
  `master.signal` is present (else defers); `analyze_set` fills `master.signal` from a live `read_meter` when
  the tap is connected; mastering ruleset got a real `loudness_target` (-16..-8 LUFS warn) + new `true_peak`
  (<= -1 dBTP fail).
- **Task 5 (device) - JS half DONE, .amxd PENDING.** `m4l/tap-server.js` (Node-for-Max relay: K-weighted
  block buffer -> ping/reset/read) + `m4l/README.md` committed. The `MCP Audio Tap.amxd` patch must be built
  by hand in Max (recipe in the plan, Task 5 Step 2: `plugin~` -> 2-stage `biquad~` K-weighting -> per-100ms
  mean-square + 4x-oversampled true-peak -> `[node.script tap-server.js]`). **NEXT ACTION = build the .amxd,
  drop it on the Master, live-verify** (`measure_loudness` integrated LUFS vs Live/Youlean within +/-0.5 LU;
  `analyze_set` mastering rules un-defer). Then RELEASE as an additive minor (in-tree 0.6.0; this is a new
  feature -> next tag; confirm latest shipped tag first).
- **Task 6 (docs) DONE:** tool-index + docs-site regenerated (112 tools / 15 categories), `docs/index.md`
  hardcoded counts bumped (108->112, 14->15), stale `analyze_set` docstring fixed, README + install note,
  this PROGRESS entry. K-weighting coefficients are 48k-only (non-48k drift = a live-verify item).

---

**Track analysis feature - SHIPPED in v0.6.0 (2026-06-12).** PR #18 squash-merged to `main` (@ffa516d);
released as **v0.6.0** (@4cfbf33 "track analysis"; tag + GitHub release created, marketplace `ableton` ref
bumped v0.5.0 -> v0.6.0 + README rebuilt + pushed @e278603 in robworks-claude-code-plugins). Version bumped
0.5.0 -> 0.6.0 across pyproject/plugin.json/uv.lock; docs landing-page counts refreshed (108 tools, 14
categories). NOTE: v0.5.0 had already shipped (robustness/batch/envelope) BEFORE this feature, so analysis
shipped as a follow-up minor, not folded into v0.5.0. CODE COMPLETE + OFFLINE-VERIFIED (399 passed) +
LIVE-VERIFIED. New `/ableton:analyze [focus]` skill + `analyze_set` MCP tool (tool count 107 ->
108) that checks the open set against curated best-practice rulesets across mixing/mastering/sound_design/
health and emits a domain-sectioned report. Design = rules-as-data: declarative JSON rulesets
(`ableton_mcp_max/rulesets/*.json` + cited `sources.md`) run by a fixed predicate evaluator. Architecture:
remote `get_analysis_snapshot` (one-shot whole-set read) -> server `normalize_snapshot` (linear vol -> dB,
reserves `signal:null` for a future M4L audio-tap) -> `evaluate_rules` -> `{snapshot, findings,
manual_rules, deferred_rules, summary}` in the `{ok,data}` envelope. Config-based checks only (the LOM
exposes no audio signal); loudness/true-peak/masking rules are `deferred` and surfaced honestly under
"Needs metering". Pure modules `analysis_utils.py` + `ruleset_utils.py` (server-side-only), fully
unit-tested: offline **399 passed** (added test_analysis_utils / test_ruleset_utils / test_snapshot_normalize
/ test_analyze_tool). Remote half py_compile-clean + installed (`install_remote_script.sh` ran;
backup -> ~/.ableton-mcp-rs-backups). Spec `docs/superpowers/specs/2026-06-11-track-analysis-rulesets-design.md`,
plan `docs/superpowers/plans/2026-06-11-track-analysis-rulesets.md`. Built via subagent-driven TDD
(11 tasks, two-stage review each; review caught real remote-handler bugs: hasattr->try/except,
instrument detection via `device.type`, group-before-midi classification). **LIVE-VERIFY PASS (2026-06-12):**
Claude-launched Live (blank default set: 4 tracks 1-MIDI/2-MIDI/3-Audio/4-Audio, returns A-Reverb/B-Delay,
empty master), installed remote handler confirmed identical to working tree. `analyze_set(all)` returned a
correct snapshot (types classified right, 0.85 linear -> 0.0 dB unity, routing MIDI=No Output / audio=Master,
`signal:null` everywhere) and correct auto-findings: `mastering.limiter_present` FAIL (empty master chain),
`sound_design.has_instrument` warn x2 (empty MIDI tracks), `health.track_named` warn x4 (default names),
fader_headroom/returns_present/device_count/no_leftover_solo PASS. Deferred `mastering.loudness_target`
honestly flagged "needs metering"; summary tallies matched the findings list (pass4/fail1/warn7/manual3/
deferred1). **NEXT = finish branch (PR/merge into origin/main, which is already at v0.5.0 @89eb094).** The
branch is origin/main + 10 analysis commits; `uv.lock` synced 0.4.0->0.5.0. Release: additive (non-breaking)
on top of the v0.5.0 base.

**Current focus:** Robustness/Efficiency/Polish initiative (post-v0.4.0) - Phases A-E ALL MERGED to
`main` AND LIVE-VERIFIED (2026-06-11; offline 353/353 + live-tested against Live 11.3.43). Branch
`feat/connection-robustness` fast-forward-merged + deleted; repo settled, working tree clean. A public
GitHub Pages docs site is live (see below). Phases 0-11 + all preset-patch rack tools (through v0.4.0,
rack macro-mapping v2) remain SHIPPED, released, marketplace ref bumped, live-verified. Plan:
`docs/superpowers/plans/2026-06-07-robustness-efficiency-polish.md`. (Built order was A -> B -> C -> E -> D.)

**Live-verify results (2026-06-11):** ALL PASS. (A) After kill+reopen Live mid-session, a single
get_session_info auto-recovered on the first call - transparent reconnect to the new Live with no manual
retry; standalone set_mixer_property write+separate-readback also confirmed. (B) A 5-member batch
(create_midi_track -> set_track_name -> create_clip -> add_notes_to_clip -> set_mixer_property) returned
count=5/completed=5/failed_index=-1 in one round-trip with all side effects landed (verified via separate
reads); stop_on_error batch with a bad middle member returned completed=1/failed_index=1, ran member 0,
skipped member 2 (confirmed vol applied, pan untouched). (C) set_song_position returned the stale 0.0
(expected write-lag) but a separate get_transport read back 8.0 - conditional settle intact.
**Setup bugs found+fixed live (committed 024d524):** `install_remote_script.sh` (1) `chown` failed under
a clobbered PATH -> install left root-owned (Live skips it); (2) wrote backups INSIDE the Remote Scripts
dir, where Live tried to `import AbletonMCP.bak.<ts>` -> SyntaxError every launch (22 had accumulated).
Both fixed (absolute chown, backups -> `~/.ableton-mcp-rs-backups`, auto-relocate strays, clear pycache).
NOTE: the AbletonMCP Control Surface must be selected in Live once; it then auto-rebinds 9877 on relaunch.

**Deferred polish sweep - DONE + LIVE-VERIFIED (2026-06-11; PR #17 squash-merged at 232df35).** Three
commits on `feat/polish-sweep` (merged + deleted): (1) reader response limits - `get_arrangement_clips`/
`get_browser_items_at_path`/`get_browser_tree` take `limit` (default 200) + report
`count`/`returned`/`truncated`; tree now returns a flattened depth-first JSON node list, not text.
(2) uniform return envelope - EVERY tool returns `{"ok":true,"data":...}` / `{"ok":false,"error":...}`
(new `_ok`/`_err`; documented centrally in best-practices + tool-index; per-tool "Returns JSON {...}"
now describes the `data` payload). (3) additive descriptive index params - `track_index`/`scene_index`/
`cue_index` canonical with `index` kept as a legacy alias (`_resolve_index`). Offline 364/364
(+`tests/test_server_helpers.py`). Live-verify ALL PASS: items limit count=14/returned=3/truncated=true;
read `{ok,data}` + bad-track `{ok:false,error}` + batch `{ok,data}`; both alias forms work, conflict
rejected, both delete forms work. Done with a 2-pass regex transform (caught + fixed a self-inflicted
`_ok` self-recursion). gh = ringo380.

**Next action:** nothing functional queued - full feasible LOM coverage + polish complete. The envelope is
a BREAKING output-contract change, so the next RELEASE should bump v0.4.0 -> **v0.5.0** (then
`gh release create v0.5.0` -> bump `ref` in the marketplace repo's `marketplace.json` ->
`node scripts/build-readme.js` -> push). Releases are user-triggered; not yet done.

**Docs site (shipped 2026-06-07):** GitHub Pages live at https://ringo380.github.io/ableton-mcp-max/ -
Jekyll (just-the-docs, dark Ableton theme) under `docs/`: landing + install guide + all 107 tools across
13 category pages, with built-in search. Source = `main` `/docs`. Regenerate the tool pages with
`python3 scripts/gen_docs_site.py` (AST-based; asserts every tool is categorized so it can't drift).
README + `.claude-plugin/plugin.json` homepage both link to it.

**Phase A detail (Connection robustness) - MERGED + LIVE-VERIFIED 2026-06-11, server.py-only.** What landed:
(1) `send_command` transparent reconnect split into send-phase (retry once, safe even for mutations,
command never reached Live) vs recv-phase (retry once only if idempotent); (2) removed the dead
`sendall(b'')` liveness probe; (3) `MUTATING_COMMANDS` frozenset = single source of truth (the old
server list was missing 24 real mutations, so they skipped the settle delay AND got the 10s read
timeout); a test parses the remote list + asserts equality (drift guard); (4) `_MUTATE_TIMEOUT`=15s >
remote task timeout 10s.

**Phase B (Batch protocol) - MERGED + LIVE-VERIFIED 2026-06-11 (offline 347/347; +`tests/test_batch.py`).**
BOTH halves edited. What landed: (1) remote `_dispatch_main_thread(command_type, params)`
method extracted from the inline `main_thread_task` if/elif (single-command path + batch loop now share
ONE dispatch table; else-branch raises on unknown); (2) new remote `batch` command runs members in ONE
scheduled main-thread task, honors `stop_on_error`, returns {count, completed, failed_index, results};
(3) server `AbletonConnection.send_batch()` (one round-trip, timeout scales 10+2*N, treated as a single
mutation so only send-phase retried) + `batch` MCP tool + `batch_utils.py` (validate shape, reject
empty/>64/nested-batch/non-mutation members, coerce stop_on_error). Reads + async-settle orchestrations
(cue points) are NOT batchable by design; load_drum_kit left as-is (interleaves reads). Live-verify
plan: create-track→name→load_browser_item→create_clip→add_notes batch returns 5 ordered results in one
round-trip; stop_on_error with a bad middle member returns partial + failed_index; timing < 5 separate
calls.

**Phase D (LLM-consumer polish, SAFE subset) + Phase E (offline tool tests) - MERGED; OFFLINE-VERIFIED
(353/353).** server.py + docs + tests. Landed: (1)
`commands/tool-index.md` - domain-grouped catalogue of all 107 tools, auto-generated by
`scripts/build_tool_index.py` (ast-based; asserts every tool is filed in a group, so it can't drift -
caught undo/redo when first run); includes cross-cutting reminders (device track_type asymmetry, batch,
write-lag, hot-swap). (2) Targeted docstring fixes: `get_device_parameters`/`set_device_parameter` now
state REGULAR-track-only in their own docstrings (was only in best-practices.md), + Returns shape; fixed
the lone em-dash in the `undo` docstring. (3) Phase E mock-socket harness = `tests/test_connection.py` +
`tests/test_batch.py` (FakeSocket/FakeConn) covering reconnect/idempotency/settle/batch + 2 tool-level
batch tests. **DEFERRED to a live-verified-base follow-up (intentionally NOT done blind):** the broad
~107-tool return-envelope standardization (write tools return ad-hoc strings vs JSON) and additive
param-name consistency (`index` vs `track_index`), plus source-side response limits on
get_browser_tree/get_browser_items_at_path/get_arrangement_clips - these are mechanical sweeps best
guarded by live verification of A-D first.

**Phase C (Efficiency: settle tuning) - MERGED + LIVE-VERIFIED 2026-06-11 (offline 351/351).**
server.py-only. Removed the unconditional pre-send 100ms delay for ALL mutations
(the recv blocks until Live responds anyway) and made the post-write 100ms settle CONDITIONAL: only
`_SLOW_SETTLE_COMMANDS` (the documented async-settling song/transport + structural ops) keep it; precise
writes (device params, mixer, clip notes/props, automation, rack macros, browser loads) now pay zero
artificial latency (they're synchronous within the scheduled task, already settled at response time).
`_attempt` gained `slow_settle`; send_batch passes slow_settle=True. NOTE: response-limit work (bounding
get_browser_tree/get_browser_items_at_path/get_arrangement_clips) was MOVED to Phase D so those readers
get their return-shape standardized once, not twice. Live-verify: a previously-laggy op (set_song_position)
still reads back correctly via a separate get_transport; precise writes feel snappier.

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Live-verified | 2026-05-24 |
| 1 | Device & Parameter Control | Live-verified | 2026-05-24 |
| 2 | Mixer (volume/pan/mute/solo/arm/sends/master/returns/xfade) | Live-verified | 2026-05-24 |
| 2b | Routing (input/output/monitor) | Live-verified | 2026-05-24 |
| 3 | Clip & MIDI Editing | Live-verified | 2026-05-24 |
| 3.1 | Extended note API migration (+ modify_clip_notes) | Live-verified | 2026-05-25 |
| 4 | Devices & Racks (info/delete/on-off/macros/chains) | Live-verified | 2026-05-25 |
| 4b | Preset selection (device-move dropped: no LOM API) | Live-verified | 2026-05-26 |
| 5 | Scenes, Transport, Arrangement | Live-verified | 2026-05-25 |
| 6 | Automation Envelopes | Live-verified | 2026-05-25 |
| 7 | Change Listeners (polling buffer) | Live-verified | 2026-05-25 |
| 8 | Arrangement Authoring (cue CRUD + arrangement clips) | Live-verified | 2026-05-26 |
| 9 | Track Lifecycle (create/delete/duplicate) & Undo/Redo | Live-verified | 2026-05-27 |
| 10 | Global Feel/Quant, Clip Launch Settings, View/Selection & Folding | Live-verified | 2026-05-27 |
| 11 | Capture & Recording (capture_midi/scene, session record, stop-all, tap-tempo) | Live-verified | 2026-05-27 |

## Phase 0 tools (parity, vendored) — live-verified (get_session_info + get_track_info confirmed; rest vendored unchanged from ahujasid)
- [x] get_session_info, get_track_info, create_midi_track, set_track_name,
      create_clip, add_notes_to_clip, set_clip_name, set_tempo, fire_clip,
      stop_clip, start_playback, stop_playback, load_instrument_or_effect,
      get_browser_tree, get_browser_items_at_path, load_drum_kit

## Phase 1 tools
- [x] param_utils.resolve_parameter_index (offline unit tests: 6/6 pass)
- [x] get_device_parameters (live: Wavetable, 93 params read w/ value_items)
- [x] set_device_parameter (live: by-name continuous + quantized, index clamping 999→48 all OK; values restored)

## Phase 2 tools
- [x] mixer_utils.normalize_property / validate_property (offline unit tests: 9/9 pass)
- [x] get_mixer (live: regular has arm+sends+xfade; return has sends, no arm; master volume/pan only. Returns = A-Reverb, B-Delay)
- [x] set_mixer_property (live: volume/pan clamped, mute toggle, send by index all OK; negative cases — arm-on-return, mute-on-master, send-without-index — rejected server-side with no Live mutation; values restored)

## Phase 2b tools
- [x] routing_utils.normalize/validate/resolve (offline unit tests: 9/9 pass)
- [x] get_routing (live: regular = input/output/monitor; return & master = input+output, NO monitoring_state. Fixed hasattr→try/except: Live raises RuntimeError not AttributeError for monitoring on return/master)
- [x] set_routing (live: monitor 2→1, output_type "Sends Only"→"Master" via object-assignment; negative — bogus/stale display_name — rejected with live "Available:" list; values restored)
- Note: input-routing-on-return/master validation was loosened (Live exposes those endpoints) and is unit-tested; the loosened server validation takes effect next Claude Code restart. The _assign_routing handler path itself is live-proven via output_type.

## Phase 3 tools
- [x] clip_utils.normalize_clip_property / validate_clip_property / coerce_clip_value /
      resolve_quantize_grid (offline unit tests: 24/24 pass; total suite 39/39)
- [x] get_clip_info (live: MIDI clip omits audio-only fields; verified on scratch + real clip)
- [x] get_clip_notes (live: arg order CONFIRMED via time + pitch windows; time_span<0→clip.length)
- [x] replace_clip_notes (live: clears then sets exactly the given notes, no leftovers)
- [x] remove_clip_notes (live: partial window [1,3) removed middle 2, left out-of-window notes)
- [x] set_clip_property (live: signature_numerator 4→3, looping→false, gain rejected on MIDI)
- [x] set_clip_loop (live: window set + looping re-enabled; inverted end<start rejected w/ values)
- [x] quantize_clip (live: enum INTS confirmed grid1=1/4 snap, grid3=1/8t snap; after fix+restart
      grid NAME "1/8"->int 2 snapped 0.6->0.5, i.e. straight eighth not triplet — fully confirmed)
- [x] duplicate_clip (live: copied to default target slot+1; empty-target guard rejects occupied)
- [x] delete_clip (live: scratch slots emptied, slots remain)
- [x] audio-clip properties (live: track 3/4 audio clips expose warping/warp_mode/gain/
      gain_display_string/pitch_coarse/pitch_fine; set gain 0.4->0.6 ("0.00 dB"->"8.00 dB",
      confirms gain is normalized 0-1), pitch_coarse->5, warp_mode 4->3, pitch_fine->25; all
      restored. gain on MIDI clip rejected with clear error.)
- **Note interaction (not a bug):** after set_clip_loop, clip.length reflects the loop length, so
  get_clip_notes default scan (time_span=-1→clip.length) only covers the loop region. Pass explicit
  from_time/time_span to scan beyond the loop.

## Routing reachability notes
- All track types expose input_routing_type/channel + output_routing_type/channel.
- current_monitoring_state: regular tracks only (return/master raise "no monitoring state").
- Endpoints are objects set by assigning from available_* lists (matched by display_name/identifier), never raw strings.

## Deployment state
- MCP server registered as **AbletonMCPMax** for project `abletonwork`
  (`uv run --directory ~/git/ableton-mcp-max ableton-mcp-max`); old `AbletonMCP`
  (uvx ahujasid) removed from that project.
- Remote Script installed at
  `/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/`
  (original ahujasid script backed up to `AbletonMCP.bak.*` alongside it).
- Requires: quit+reopen Live (load new handlers), restart Claude Code (load new tools).

## Phase 3 live-verification notes
- **get_clip_notes arg order CONFIRMED** = (from_time, from_pitch, time_span, pitch_span).
  Time window [0,2) returned only early notes; from_pitch=65 returned only pitches >=65.
- **get_clip_info**: MIDI clip omits audio-only fields (warp/gain/pitch) via try/except. Confirmed
  on scratch clip + real "I Remember - Chords" clip.
- **quantize_clip 1/4 CONFIRMED**: grid="1/4" -> enum int 1; note at 2.4 snapped to 2.0 (musically
  correct). Confirms 1/4 exists and QUANTIZE_GRID_MAP ordering (none=0, 1/4=1, ...) is right.
- **replace_clip_notes works** (clip correctly held only the new note afterward) BUT see dialog below.
- **GOTCHA — Live 11 legacy-note-API modal**: any WRITE via legacy set_notes/remove_notes
  (replace_clip_notes, remove_clip_notes, add_notes_to_clip, quantize) pops a modal
  ("A custom MIDI Remote Script uses an older process to modify MIDI notes...") that BLOCKS the
  Remote Script main thread -> our socket times out with "No data received" even though the edit
  succeeds. Reads (get_notes) are unaffected. Short-term: user checks "Do not show again for this
  device" + Proceed. PROPER FIX: migrate note writes to Live 11 extended API
  (set_notes_extended/apply_note_modifications) — also preserves MPE/probability/release-velocity.
  Recommend pulling this forward from a later phase.
  - CONFIRMED the modal fires on EVERY legacy note write (per-write, not one-time) unless
    "Do not show again for this device" is checked. clip.quantize does NOT trigger it (different
    code path). So replace/remove/add-notes all block per call until the box is checked.
- **quantize enum FIX (live-found)**: original QUANTIZE_GRID_MAP was wrong (had a nonexistent 1/4t,
  off-by-one beyond 1/4). Corrected to none=0,1/4=1,1/8=2,1/8t=3,1/8+1/8t=4,1/16=5,1/16t=6,
  1/16+1/16t=7,1/32=8 (confirmed: grid 1->1/4 snap, grid 3->1/8t snap). Fix is in clip_utils.py;
  takes effect after the next Claude Code restart (server-imported module, no hot reload).

## Phase 3.1 — extended note API migration (live-verified 2026-05-25)
- Migrated add/replace/remove/get note ops to Live 11 extended API
  (add_new_notes / remove_notes_extended / get_notes_extended) + `import Live` in remote script.
  **The legacy-note modal NO LONGER APPEARS on any write** (root issue resolved).
- get_clip_notes now returns note_id + probability + velocity_deviation + release_velocity.
  Live confirmed: explicit probability=0.5/release_velocity=80 on add round-trip through get;
  omitted fields default to 1.0 / 0.0 / 64.0 (server-side clip_utils.normalize_note).
- **Extended arg order CONFIRMED** = (from_pitch, pitch_span, from_time, time_span) — pitch FIRST,
  opposite the legacy get_notes. Verified via pitch-window + time-window reads.
- NEW modify_clip_notes (apply_note_modifications): live-confirmed in-place edit by note_id
  (changed only provided fields, note_id preserved, other notes untouched — no remove+re-add);
  bogus note_id rejected with "note_id(s) not found in clip: [...]".
- clip_utils: +normalize_note (defaults/clamps) +NOTE_MOD_FIELDS; offline suite 43/43.

## Phase 4 tools (Devices & Racks) — code complete, awaiting live verification
- [x] device_utils.resolve_device_index / resolve_macro / normalize_chain_property /
      validate_chain_property / coerce_chain_value / coerce_on_value
      (offline unit tests: 22/22; total suite 65/65)
- [x] get_device_info (live: Wavetable -> can_have_chains false, 93 params, is_on true;
      "Basic Analog Bass" rack -> can_have_chains true, chain_count 1, is_on true. macro_count
      now 16 after fix.)
- [x] delete_device (live: deleted "Basic Analog Bass" from track 0 -> device_count 0, track empty; re-indexes)
- [x] set_device_on (live: track 0 Wavetable off->on confirmed both ways incl. "on" string coercion; restored)
- [x] get_rack_macros (live after fix: 16 macros incl. renamed Filter Cutoff/Drive/etc., positional macro_number)
- [x] set_rack_macro (live after fix: by number 5->Drive=60, by custom name "Filter Cutoff"=100;
      macro 99 rejected with full "1=Filter Cutoff..16=Macro 16" list)
- [x] get_rack_chains (live: 1 chain "Analog" with 6 inner devices Analog/Comp/VinylDist/Delay/Delay/Reverb;
      mute/solo/volume/panning surfaced)
- [x] set_chain_property mute/solo (live: chain "Analog" mute false->true->false confirmed; restored)
- [x] set_chain_property volume/panning guard (live after fix: chain "Analog" volume rejected with clean
      "not settable (disabled by Live for this chain)"). Whether any rack chain exposes an *enabled*
      volume/panning still TBD (re-probe on a multi-chain rack later).
- **Deferred to Phase 4b:** device move (no LOM reorder API) + preset selection (browser re-load).
- **Add device** already covered by existing load_instrument_or_effect (browser load) — not re-impl.

### Live findings (2026-05-25)
- **MACRO LAYOUT (important):** a rack's parameters are `Device On`(0), then the macros
  (1..N), then `Chain Selector`(last). Macros may be RENAMED (e.g. "Basic Analog Bass" macros
  1-8 = Filter Cutoff/Filter Reso/Filter Envelope/Space/Drive/Comp/Delay/Volume; 9-16 default
  "Macro 9".."Macro 16"). Original name-prefix filter missed the renamed ones. FIXED: _rack_macros
  now enumerates by POSITION (everything between Device On and Chain Selector) and tags each with
  a 1-based macro_number; resolve_macro resolves a number positionally + a name by custom label.
- **CHAIN MIXER:** chain.mixer_device.volume/panning can be `is_enabled == False` (seen on the
  single-chain Analog rack chain) -> Live raises "Value cannot be set, the parameter is disabled".
  Handler now pre-checks is_enabled and raises a clear message. mute/solo always work.
- **load_instrument_or_effect HOT-SWAPS:** loading onto a track that already has an instrument
  REPLACES it (track 1 Lead's Wavetable was replaced by the test rack). Restore via Live undo.
- TBD: drum-rack (can_have_drum_pads) chain shape; multi-chain rack with enabled chain volume.

## Phase 4b tools (Preset Selection) — LIVE-VERIFIED 2026-05-26
Scope settled this session: **device move/reorder DROPPED as infeasible** — Live 11's LOM exposes
no device copy/paste/reorder API (`Track` has only `delete_device`; no `move_device`/clipboard).
The only technically-possible route was a fragile osascript Cmd+C/Cmd+V keystroke hack (Live must be
frontmost, UI-focus + timing dependent, breaks the socket/LOM architecture) — explicitly rejected.
Revisit if/when the project targets Live 12.
- [x] preset_utils.py (server-only pure helper): `match_preset` (direct-children match: exact →
      case-insensitive → unique substring; ValueError listing available names), `match_recursive_preset`
      (matches a query against name OR relative_path across the whole subtree; capped available list),
      `split_preset_path` (full path → (parent, leaf); ValueError on single-segment).
      Offline tests +18 → total suite 158/158.
- [x] remote_script: new READ command `get_browser_presets(path, max_depth=6)` — reuses
      get_browser_items_at_path's root-category + path-walk, then recursively collects loadable
      leaves ({name, relative_path, uri}). Read-only (direct dispatch, NOT in mutation list /
      main_thread_task). Returns same {error, available_categories} envelope on path miss.
- [x] server.py tools: `list_device_presets(path, max_depth=6, limit=100)` → get_browser_presets,
      returns {count, returned, truncated, presets} (capped to `limit` — factory devices expose
      hundreds; raw dump overran the MCP token limit at 419 presets). `load_preset(track_index, path,
      name=None)` → get_browser_presets(folder) → `match_recursive_preset` → load_browser_item.
      HOT-SWAPS like load_instrument_or_effect. (2 tools cover all 3 requested capabilities —
      load-by-name and load-.adv/.adg are the same browser-item/load_browser_item op.)
- Plan: `~/.claude/plans/let-s-work-on-phase-expressive-catmull.md`.
- **Code review (medium, 2026-05-26):** found list/load path-semantics mismatch — `list_device_presets`
  lists presets recursively (all 419 Wavetable presets nested in subfolders) but `load_preset`
  originally resolved only against DIRECT children via get_browser_items_at_path, so the documented
  list→load-by-name workflow could not load ANY factory Wavetable preset (live-reproduced:
  "No loadable presets at this path."). **Fixed**: load_preset now resolves recursively via
  get_browser_presets + match_recursive_preset (matches name or relative_path). Also capped
  list_device_presets output (76KB → bounded).
- **Live verification (2026-05-26, scratch MIDI track), PRE-FIX server.py:**
  list_device_presets('instruments/Wavetable') → 419 presets (all nested, relative_path like
  'Ambient & Evolving/Dark Swarm.adg'); load_preset by name against the category path FAILED
  ("No loadable presets at this path" — the bug). Workarounds confirmed working live: folder-path +
  name, and full-path form (split_preset_path); hot-swap confirmed (get_device_info →
  InstrumentGroupDevice rack); negative match → clean error listing available names; delete_device →
  device_count 0 (restore). NOTE: a scratch MIDI track was left in the open project (no delete_track
  tool) — remove via Live undo.
- **POST-FIX LIVE-VERIFIED (2026-05-26, after Claude Code restart, scratch MIDI track):** the exact
  pre-fix failure now works — load_preset(track, 'instruments/Wavetable', name='Dark Swarm.adg') →
  loaded 'Ambient & Evolving/Dark Swarm.adg'; relative_path substring ('Bass/Talking') → uniquely
  resolved 'Bass/Talking 808 Bass.adg'; hot-swap confirmed (get_device_info → InstrumentGroupDevice);
  list cap: limit=3 → {count:419, returned:3, truncated:true}+hint, default limit=100 → returned:100
  WITHOUT overrunning the MCP token limit (pre-fix 419-dump errored at 76KB). delete_device restore OK.
  Offline suite 158/158.

## Device parameter reachability notes
- Wavetable: 93 automatable params exposed. Quantized params (Device On, Osc On,
  Filter Type/LP-HP/Slope, Sub Transpose, Loop Modes, LFO Shape/Sync/Retrigger)
  expose value_items and are settable by integer index. Continuous params settable
  by float; out-of-range values clamp to min/max. Settable by name (case-insensitive)
  or index. No menu-only/unreachable controls observed at the device top level.

## Phase 5 tools (Scenes, Transport, Arrangement) — ALL live-verified 2026-05-25
- [x] scene_utils.normalize_scene_property / coerce_scene_value;
      transport_utils.parse_time_signature / resolve_cue_direction / coerce_song_time /
      coerce_jump_beats / coerce_loop_fields / coerce_punch_fields
      (offline suite 93/93). Reuse device_utils.coerce_on_value for bool toggles.
- **Scenes (7):**
  - [x] get_scenes (live: 9 scenes; per-scene tempo/time-sig surface -1 sentinel when not overridden)
  - [x] fire_scene (live: launched scene 0, is_playing→true; index 99 rejected "out of range (0..8)")
  - [x] create_scene (live: -1 appended, count 9→10)
  - [x] delete_scene (live: count 10→9; range-guarded)
  - [x] duplicate_scene (live: count 9→10, copy after source)
  - [x] set_scene_name (live: scene 2 ""→"VERIFY"→"" restored)
  - [x] set_scene_property (live: color/tempo/tempo_enabled/time_signature all applied;
        aliases bpm/time_sig/colour fold correctly; bad denom 4/3 + bogus prop rejected server-side)
- **Transport (8):**
  - [x] get_transport (live: full state incl. session_record/song_length/back_to_arranger)
  - [x] continue_playback (live: resumed from position, advanced playhead)
  - [x] set_metronome (live: off→on→off; reads back fresh)
  - [x] set_arrangement_record (live: record_mode on→off — NOTE arming starts playback)
  - [x] set_session_record (live: on→off — NOTE arming starts playback)
  - [x] set_punch (live: in/out true→false; both-None guard server-side)
  - [x] set_song_position (live: jumped to 8 then 64; negative -1 rejected server-side)
  - [x] jump_by (live: +/- beats, -4 from 8→4)
- **Arrangement (5):**
  - [x] get_cue_points (live: 2 locators locator1@32, locator2@64)
  - [x] set_arrangement_loop (live: enabled/start/length applied, only-provided fields;
        all-None guard server-side; restored to original off/8/16)
  - [x] jump_to_cue (live: prev 64→32, next/forward 32→64; "sideways" rejected)
  - [x] back_to_arrangement (live: back_to_arranger override true→false re-engages arrangement)
  - [x] re_enable_automation (live: returns re_enabled true, no error — LOM call present in build)

### Phase 5 live findings (2026-05-25)
- **Verify-or-drop flags ALL resolved:** re_enable_automation() exists & works; back_to_arranger=0
  clears the override; jump_to_next_cue()/jump_to_prev_cue() both work (used instead of cue.jump()).
- **Return-value lag (cosmetic):** song-level property WRITES (record_mode, session_record, punch_in/out,
  current_song_time, loop, back_to_arranger) succeed but the handler's same-task read-back returns the
  PRE-write value — a follow-up get_transport always shows the correct value. metronome reads fresh.
  The mutation itself is reliable; only the returned confirmation dict can be stale. Not worth a fix
  (Live applies the property change asynchronously even within schedule_message).
- **Arming record auto-starts playback:** set_arrangement_record(on) and set_session_record(on) begin
  playback immediately. Tests must stop + restore promptly. song_length stayed 232.0 → nothing recorded
  (no armed tracks).
- **Per-scene time_signature cannot be reset to the -1 "inherit" sentinel** (numerator must be >=1):
  once set it's a permanent override. Live API limitation — set_scene_property can change it but not clear it.
- **Live snaps scene color to its palette:** set color 16711680 stored as 16728642 (nearest entry).

## Phase 6 tools (Automation Envelopes) — ALL live-verified 2026-05-25
- [x] automation_utils.normalize_clip_location / normalize_target_type /
      normalize_mixer_target / coerce_resolution / coerce_time / coerce_duration /
      coerce_value / normalize_breakpoints (offline suite 114/114; 21 new)
- [x] get_automation (live: sampled read; has_envelope false→true; windowed
      from_time/time_span read confirmed; device + mixer targets)
- [x] set_automation (live: single point + batch points list; auto-tile fix below)
- [x] clear_automation (live: range clear + full-envelope clear)
- [x] create_automation_envelope (live: created true then false — idempotent)
- [x] clear_all_automation (live: wiped Macro 1 + Track Volume envelopes → has_envelope false)
- Targets verified: device param by NAME ("Macro 1" on an Instrument Rack — confirms
  macros automate through the device path), mixer "volume" → "Track Volume",
  mixer "send" send_index=0 → "A-Reverb".

### Phase 6 live findings (2026-05-25)
- **insert_step needs duration > 0 — duration=0 is a NO-OP.** Live's
  AutomationEnvelope.insert_step(time, duration, value) writes a FLAT segment
  [time, time+duration); a zero-width step creates the envelope but holds no value
  (read back 0). There are NO linear ramps in the LOM — flat tiles are the only
  write primitive (a multi-point list draws a staircase, not a ramp).
- **FIX (live-found, in `_set_automation`): auto-tile zero/negative durations.** Points
  are sorted by time; a point with duration<=0 fills to the NEXT point's time (last
  point fills to clip.length; 1/32-beat fallback if that gap is <=0). So
  `set_automation(time=0, value=64)` now holds 64 across the whole clip, and a bare
  `points` list (no durations) draws the obvious staircase. Verified: value-only point
  held 64 over [0,4]; staircase 20/80/127 tiled at [0,1.5)/[1.5,3)/[3,4).
- **value_at_time left-edge boundary:** sampling at the EXACT start of a step returns
  the PRE-step value (e.g. t=0.0 reads 0 even when a step starts at 0). Samples inside
  the step are correct. Cosmetic; sample slightly inside a region to see its value.
- **Arrangement path:** `track.arrangement_clips` EXISTS and indexes (a bad index
  returns our clean "Arrangement clip index out of range", not AttributeError). The
  resolver is proven; full read/write on an arrangement clip not exercised (the test
  set had none) — re-verify when an arrangement clip is present.
- Negatives all clean server-side (no Live mutation): bad clip_location, mixer "send"
  without send_index, empty points list.
- **No legacy modal / main-thread stall** on any automation write (unlike the old
  legacy-note API) — envelope writes go through schedule_message cleanly.

## Phase 7 tools (Change Listeners — polling buffer) — CODE COMPLETE, awaiting live verify
Approach: Live's observer API is push-based; this MCP is request/response. Remote Script attaches
real Live listeners whose no-arg callbacks read the new value and append a change event to a
bounded per-listener deque (LISTENER_BUFFER_MAX=512; overflow evicts oldest + bumps `dropped`).
Claude drains on demand. Zero protocol changes. (Plan:
`~/.claude/plans/let-s-plan-out-phase-nifty-widget.md`.)
- [x] listener_utils.py (server-only pure helper): normalize_scope, normalize_listener_property
      (alias folding), build_descriptor (canonical {target_kind, listener_method, remove_method,
      readback, mixer_sub, selectors}; reuses mixer_utils track-type asymmetry), coerce_max_events,
      needs_device_resolution. Offline tests 26 new → total suite 140/140.
- [x] server.py: register_listener, poll_changes, unregister_listener, list_listeners (device-param
      identifier resolved via get_device_parameters + param_utils, like _resolve_auto_target).
- [x] remote_script: registry dict + threading.Lock + monotonic seq/id in __init__; register/
      unregister are MUTATIONS (in the elif list + main_thread_task — Live add_/remove_*_listener
      must run on main thread); poll/list are DIRECT reads (buffer-only, skip main thread); navigation
      `_listener_target_object` per target_kind (song/song_view/track/track_mixer/clip/clip_slot/
      device_param); `_make_listener_cb` factory + `_listener_emit` under lock; detach-all in disconnect.
- Scopes wired: transport (is_playing, current_song_time [high-volume], tempo, metronome,
  record_mode, session_record, loop), mixer (volume/pan/mute/solo/arm — arm regular-only),
  clip (playing_status, name, notes, has_clip, selected_scene via song.view), device (param value).

### Phase 7 live-verification results (2026-05-25 — ALL PASS)
- [x] Transport: is_playing fired true (start) → false (stop); tempo fired 128 then 120 on set_tempo.
      seq monotonic across listeners, dropped=0.
- [x] Mixer: volume on track 0 (regular) fired 0.85→0.7 on set_mixer_property (restored 0.85).
      arm on RETURN track 0 rejected at register time: "Property 'arm' not supported on return
      tracks. Supported: crossfade_assign, mute, pan, send, solo, volume" (no Live mutation).
- [x] Clip: playing_status on track0/slot0 fired true then false on fire_clip (clip is 0.44 beats so
      it retriggered → two events). Stopped clip after.
- [x] Device: loaded Analog onto empty MIDI track 1; register scope=device property=value
      parameter="Volume" resolved to param[3]; set_device_parameter 0.7→0.5 fired value=0.5.
      Scratch device deleted after (track 1 empty again).
- [x] High-volume / dropped: current_song_time during playback hit the bounded deque ceiling —
      pending capped at 512 with dropped climbing (393→774 across two polls). max_events=3 returned
      exactly the 3 oldest (remaining 509). Confirms LISTENER_BUFFER_MAX=512 + oldest-eviction.
- [x] list_listeners showed all 6 with target+pending+dropped; unregister_listener (no id) removed
      all 6; subsequent list_listeners count 0 and poll_changes empty (no further accrual).
- [x] Negatives: bad scope ("Unknown scope 'bogus_scope'. Valid: transport, mixer, clip, device"),
      bad transport property ("Unknown transport property ... Valid: current_song_time, is_playing,
      loop, metronome, record_mode, session_record, tempo"), mixer w/o track_index ("mixer listener
      for 'volume' requires track_index") — all rejected server-side.

### Phase 7 live findings (2026-05-25)
- **listener_id is a simple monotonic "L<n>"** assigned per register; persists until unregister.
- **`pending` caps at LISTENER_BUFFER_MAX (512); `dropped` is cumulative** since last drain of that
  listener — high-volume targets (current_song_time) overflow fast, so poll often or expect drops.
- **poll seq is a global monotonic counter** shared across listeners (not per-listener), so event
  ordering is total across the whole registry.
- **arm validation happens at REGISTER time** for return/master (reuses mixer_utils asymmetry), not
  at poll — a rejected register never attaches a Live listener.

## Phase 8 tools (Arrangement Authoring) — ALL live-verified 2026-05-26
Extends Phase 5 from cue reads/navigation into cue + arrangement-clip editing. Pure helper
`arrangement_utils.py` (coerce_time, coerce_index, cue_exists_at; offline tests +14 → suite 172/172).
- **Cue points (2 — rename DROPPED):**
  - [x] create_cue_point(time) — server orchestrates get_transport → set_song_position(time) →
        create_cue_at_playhead → restore playhead. Live: created cue@16 alongside existing
        locator1@32 + locator2@64 (none disturbed), playhead restored to 8; re-call → created:false
        reason:exists (idempotent, never deletes).
  - [x] delete_cue_point(index) — server looks up cues[index].time → set_song_position → toggle off →
        restore. Live: removed cue@16, other two survived, playhead restored; index 999 → clean
        server-side "out of range (0..1)".
  - **set_cue_point_name DROPPED:** `CuePoint.name` is READ-ONLY in the Live 11 LOM ("can't set
        attribute"). Locator names are UI-only; no API write path.
- **Arrangement clips (3):**
  - [x] get_arrangement_clips(track_index) — Live: count:0 baseline; lists index/name/start_time/
        end_time/length/is_midi_clip.
  - [x] duplicate_clip_to_arrangement(track_index, source_slot_index, destination_time) — Live:
        placed a session clip at beats 0 then 8, returns new_clip{name,start,end} (destination_time
        confirmed in BEATS); empty source slot → clean "No clip in session slot N on track M".
  - [x] delete_arrangement_clip(track_index, clip_index) — Live: deleted + remaining clips re-index
        (clip@8 became index 0); index 999 → clean "out of range".
- Spec: `docs/superpowers/specs/2026-05-26-phase-8-arrangement-authoring-design.md`;
  Plan: `docs/superpowers/plans/2026-05-26-phase-8-arrangement-authoring.md`.

### Phase 8 live findings (2026-05-26) — design changes driven by live behavior
- **In-task `current_song_time` writes are async (Phase 5 gotcha, confirmed harder here):** the
  original one-handler move→toggle→restore for cues FAILED — `set_or_delete_cue()` fired at the
  STALE playhead position, deleting the wrong cue (test: create_cue_point(16) with playhead at 64
  deleted locator2@64 and created nothing). Fix: split into separate socket commands; the playhead
  settles BETWEEN commands. Handlers `_create_cue_at_playhead`/`_delete_cue_at_playhead` now operate
  only at the already-settled playhead; the server does the positioning + restore.
- **`set_or_delete_cue()` takes NO time arg** — it toggles at the playhead; there is no create-at-
  arbitrary-time call. Pre-check cue_points to decide create vs. (avoid) delete.
- **CuePoint.name read-only** → rename infeasible (dropped). New cues get Live's auto-name ("1","2").
- **cue_points list is insertion-ordered, not time-sorted** (index 2 can be at an earlier time than
  index 0) — index is stable for delete; don't assume chronological order.
- **duplicate_clip_to_arrangement returns the new Clip** and re-reads of arrangement_clips within the
  same task reflect it (unlike song-position). delete_clip(clip) re-indexes the list.

## Phase 9 tools (Track Lifecycle & Undo/Redo) — ALL live-verified 2026-05-27
Closes the standing "no delete_track" gap (scratch tracks no longer need user Cmd+Z). Pure helper
`track_utils.py` (coerce_create_index: None/-1 → append, else >=0; coerce_track_index: >=0;
offline tests +11 → suite 183/183). All 7 LOM calls confirmed in 11.0.0.xml. Separate tools per
track type (1:1 with LOM), per design.
- **Creates (3):**
  - [x] create_audio_track(index=-1) — live: appended at index 7 → "8-Audio", track_count 7→8.
  - [x] create_return_track() — live: appended at return index 2 → "C-Return", return_count 2→3.
  - [x] create_midi_track — PARITY ONLY (Phase 0 tool already had index=-1; no change this phase).
- **duplicate_track(index) (1):** live: duplicate_track(7) → new_index 8 "9-Audio", count 8→9.
  Confirms new_index derived from `song.view.selected_track` (LOM duplicate_track returns None).
- **Deletes (2):**
  - [x] delete_track(index) — live: deleted 8 then 7, remaining_count 9→8→7, collection re-indexes.
  - [x] delete_return_track(index) — live: deleted return 2, remaining_count 3→2.
- **Undo/redo (2):**
  - [x] undo() / redo() — live: create → undo {undone:true, can_redo:true} → redo {redone:true,
        can_redo:false}. Both guarded by can_undo/can_redo precheck (clean no-op when empty).
- **Negatives:** delete_track(999) → handler-side "Track index out of range (0..6)"; duplicate_track(-5)
  → server-side coercion "Index must be >= 0; got -5" (no socket call). All scratch tracks cleaned up
  via the new delete tools → set restored to baseline 7 regular / 2 returns.
- Spec: `docs/superpowers/specs/2026-05-27-phase-9-track-lifecycle-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-9-track-lifecycle.md`.

### Phase 9 live findings (2026-05-27)
- **Track-structural undo readback is STALE (new, important):** immediately after `undo()` of a
  track create, a follow-up `get_session_info` returned a TRANSIENT wrong count (9 regular / 3 returns
  — the pre-delete peak) instead of the settled value; a second read showed the correct count. This is
  the song-property-write-lag class (Phase 5) now confirmed for track-collection structure after undo.
  The undo/redo MECHANISM itself is reliable (undone/redone flags + can_undo/can_redo correct, redo
  reinstated the track and settled to the right state). **Verify structural state with a second read
  after undo/redo; don't trust the first post-undo count.**
- **undo is GLOBAL** (documented in the tool): it walks Live's whole undo stack including user
  hand-edits; the can_undo precheck only prevents erroring on an empty stack, it does not scope to MCP.
- **duplicate_track selects the new track**, so `song.view.selected_track` is a reliable in-task source
  for new_index/name (LOM duplicate_track itself returns None).

## Phase 10 tools (Global Feel/Quant, Clip Launch, View/Selection & Folding) — ALL live-verified 2026-05-27
Gap-audit phase. Two candidates dropped as infeasible in Live 11: **warp-marker editing**
(`Clip.warp_markers` read-only; no add/remove/move_warp_marker methods) and **follow actions**
(`follow_action*` absent from 11.0.0 LOM). Capture/recording (capture_midi/capture_and_insert_scene/
trigger_session_record/stop_all_clips/tap_tempo) is feasible but DEFERRED by user. Offline suite +19 → 202.
- **Group A — global feel/quant (`transport_utils.py`, 5 tools):**
  - [x] set_groove_amount(amount) — live: 1.0→0.5→1.0 confirmed via get_transport. 0–1 clamp.
  - [x] set_swing_amount(amount) — live: 0.0→0.5→0.0 confirmed. 0–1 clamp.
  - [x] set_clip_trigger_quantization(value) — live: name "1/4"→7 confirmed; default read=4 (1_bar).
        Confirms CLIP_TRIGGER_QUANTIZATION_MAP matches standard Live.Song.Quantization ordering.
        Bad name → clean server-side error listing all options + "(or an int 0-13)".
  - [x] set_midi_recording_quantization(value) — live: name "1/8"→2 confirmed (matches QUANTIZE_GRID_MAP).
  - [x] set_nudge(direction, active) — live: up true→false confirmed via get_transport nudge_up flag.
  - [x] get_transport extended (+7 reads): groove_amount, swing_amount, clip_trigger_quantization,
        midi_recording_quantization, count_in_duration (READ-ONLY, read 0), nudge_up, nudge_down — all present.
- **Group B — clip launch settings (extends set_clip_property/get_clip_info, NO new tool):**
  - [x] launch_mode/launch_quantization/legato/velocity_amount — live on a scratch MIDI clip (track 6):
        launch_mode=3, launch_quantization=2, legato=true, velamount alias→velocity_amount=0.5; all
        read back via get_clip_info. NOT rejected as audio-only (confirms valid on MIDI). Also read on
        an audio clip (track 0). Scratch clip deleted after.
- **Group C — view/selection & folding (`view_utils.py`, 6 tools):**
  - [x] set_selected_track — live: regular track 0, AND return 0 ("A-Reverb") confirmed; restored to track 6.
  - [x] set_selected_scene — live: scene 1 set (later re-coupled to 0 by highlighted-slot, see findings).
  - [x] set_detail_clip — live: track 0/slot 0 → detail_clip "FHP_DARK SYNTH3_C"; empty slot (track 6) →
        clean "No clip in slot 0 on track 6".
  - [x] set_highlighted_clip_slot — live: track 0/scene 0 → has_clip true.
  - [x] set_track_fold — FULLY verified (2026-05-27): negative (non-group → clean "not a group track")
        AND positive on hand-made group track "3-Group" (idx 2): bool true/false + int 1/0 round-trip,
        fold visually confirmed collapsed in Live. (Group tracks need ⌘G by hand — no LOM create API.)
  - [x] get_view_selection() — live: selected track index/name, scene index, detail_clip name,
        highlighted-slot has_clip all returned.
  - [x] get_track_info extended (+3 reads): is_foldable/is_grouped present on all tracks read;
        fold_state omitted on non-foldable tracks (getattr raised → defensive skip).
- Spec: `docs/superpowers/specs/2026-05-27-phase-10-feel-launch-view-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-10-feel-launch-view.md`.

### Phase 10 live findings (2026-05-27)
- **Quantization enums CONFIRMED:** clip_trigger_quantization default reads 4 = `1_bar`; name "1/4"→7.
  This matches the standard Live.Song.Quantization ordering encoded in CLIP_TRIGGER_QUANTIZATION_MAP
  (none=0, 8/4/2_bars=1/2/3, 1_bar=4, 1/2=5, ... 1/4=7, ... 1/32=13). midi_recording_quantization "1/8"→2
  matches the already-confirmed clip_utils.QUANTIZE_GRID_MAP. **launch_mode/launch_quantization ints
  round-trip** (set 3/2, read 3/2); exact UI labels not visually confirmed but the int path is reliable.
- **detail_clip read couples to the highlighted slot:** in a batch, calling set_highlighted_clip_slot
  AFTER set_detail_clip transiently cleared detail_clip (read null); setting detail_clip alone reads back
  correctly. Highlighting a slot also re-selects its track+scene (so a prior set_selected_scene gets
  overridden). Set these LAST / individually if you need the read to stick. Setters themselves are reliable.
- **fold_state CLOSED (2026-05-27):** verified on a hand-made group track ("3-Group", idx 2) — bool
  true/false AND int 1/0 both round-trip; fold visually confirmed in Live; non-foldable grouped child
  (idx 3) rejected cleanly. Group tracks can't be created via LOM (no API) — make via ⌘G by hand.
  CAVEAT: `get_track_info` crashes on group tracks (reads `.arm`, which group tracks lack) — separate
  pre-existing bug, see header. fold_state verification used the setter's own echo + visual check, not
  get_track_info.
- **Song-property-write lag (Phase 5) did NOT bite Group A here** — get_transport read back the new
  groove/swing/quant/nudge values correctly on the first follow-up read. Still prefer the separate read.

## Phase 11 tools (Capture & Recording) — ALL live-verified 2026-05-27
Closes the capture/recording set deferred during the Phase 10 gap-audit. All 5 LOM calls confirmed in
11.0.0.xml (Song methods). Pure helper additions in `transport_utils.py` (offline suite +8 → 210).
- **5 tools (all song-level mutations):**
  - [x] capture_midi(destination="auto") — live: with NO material → safe no-op (captured:true, nothing
        created); all 3 destinations (auto/session/arrangement) resolve via getattr + execute. POSITIVE
        test: user played MIDI into an armed scratch track → can_capture_midi flipped true →
        capture_midi("session") created an 8.0-beat MIDI clip in the armed track's slot. Scratch track deleted.
  - [x] capture_and_insert_scene(mode="all") — live: fired track-0 audio clip (playing) → captured a new
        NON-empty scene inserted at index 1 (after selected scene 0); scene_count 9→10. Captured scene deleted.
  - [x] trigger_session_record(record_length=4) — live: on an armed scratch MIDI track → auto-started
        playback AND created a clip of EXACTLY 4.0 beats (fixed-length recording finished, clip looping).
        Scratch track deleted. record_length=0 rejected server-side ("must be > 0").
  - [x] stop_all_clips(track_index=None, quantized=True) — live: song-level (fire clip → stop-all,
        quantized=false → clip stopped, song keeps playing) AND track-scoped (track_index=0 → scope:track).
        Negatives: track_index=99 → handler "Track index out of range (0..7)"; track_index=-5 → server-side
        "Index must be >= 0" (no socket call).
  - [x] tap_tempo() — live: executes cleanly (tapped:true, tempo echoed). A SINGLE tap does NOT change
        tempo (Live needs successive taps to compute an interval) — call repeatedly in time to set tempo.
- **get_transport +3 reads:** can_capture_midi, is_counting_in, session_record_status — all present (live:
  can_capture_midi false at rest, flipped true after playing MIDI; session_record_status int 0).
- **Enum handling:** CaptureDestination/CaptureMode int values are UNDOCUMENTED in the LOM, so the server
  validates the NAME (transport_utils.resolve_capture_destination/resolve_capture_mode — return the name,
  not an int) and the Remote Script resolves it via getattr(Live.Song.CaptureDestination, name). Deliberate
  deviation from the usual "send ints" convention; keeps the enum source-of-truth in Live.
- **transport_utils helpers:** resolve_capture_destination (None→auto), resolve_capture_mode (None→all),
  coerce_record_length (None→omit; else float >0). stop_all_clips reuses coerce_on_value +
  track_utils.coerce_track_index.
- Spec: `docs/superpowers/specs/2026-05-27-phase-11-capture-recording-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-11-capture-recording.md`.
- **Live-test reminders:** confirm effects via SEPARATE follow-up reads (song-property-write lag);
  capture tools do nothing on an empty blank set (need playing material); clean up captured clips/scenes
  + restore the set; stop session-record promptly (auto-starts playback).

## Preset-patch backdoor (initiative — separate from numbered Phases)
Reach Ableton controls absent from the LOM `device.parameters` API by patching gzipped
preset XML (.adv/.adg), writing to the User Library, and loading via the browser.
Shared pure core: `ableton_mcp_max/preset_patch.py` (set_attr/set_manual/scope/get_attr + validators).

- **Wavetable + Simpler** (committed `30570cd`): `list_wavetable_tables`, `create_wavetable_preset`
  (osc table / unison mode / voices — none automatable), `create_simpler_instrument` (sample ref
  injected into empty `<SampleParts/>`). `wavetable_preset_utils.py` / `simpler_preset_utils.py`.

- **Rack macro-mapping & zones — Phase A: LIVE-VERIFIED 2026-05-29** (branch `feat/preset-patch-backdoor`).
  Pure XML in `rack_preset_utils.py` (depth-aware branch scanner finds chain-level zones that are
  DIRECT children of a branch, ignoring nested sampler multisample KeyRanges); 4 tools in server.py.
  Spec: `docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md`;
  Plan: `docs/superpowers/plans/2026-05-29-rack-preset-macro-mapping.md`. Offline 293/293.
  - [x] inspect_rack_preset — live: "808 Drifter" → instrument, 8 visible macros, all 16 read
        (named + color + default; unnamed color -1), 1 chain w/ key/vel/selector zones.
  - [x] clone_rack — live: 808 Drifter → User Library `Instruments/Instrument Rack/MCP RackTest.adg`
        (category/folder derived from rack_type); browser_path returned.
  - [x] rename_rack_macros — live: macro 1→"MCP One" color 5, macro 2→"MCP Two & Co" default 100;
        `&` XML-escape round-trips; unlisted macros preserved.
  - [x] set_rack_zones — live: chain 0 key→[24,96], velocity→[1,100]; file round-trips via inspect.
  - [x] load_preset (existing tool) — live: loaded MCP RackTest onto scratch MIDI track 3 first try
        (User Library already indexed). LOM `get_rack_macros` confirmed device "MCP RackTest" with
        "MCP One" / "MCP Two & Co"; full device chain intact. Scratch track + test preset cleaned up.
  - **Rack-type detection is POSITION-based** (earliest device tag = top-level rack's device): factory
    "drum kits" (e.g. Acuff Kit) are actually INSTRUMENT racks wrapping a nested Drum Rack (master-bus
    macros like "Master EQ"/"Master Comp") → correctly detected as `instrument`. A bare top-level
    DrumGroupDevice (only from saving a raw Drum Rack) detects as `drum`; its DrumBranchPreset pads
    carry direct-child key/vel zones (probe-confirmed), so `has_key_velocity=True` is correct.
  - **Phase B (macro→parameter MAPPINGS): save-diff experiment DONE 2026-05-29 → GO (cleanly patchable).**
    Encoding cracked: a mapping is a self-contained `<KeyMidi>` block injected into the TARGET PARAMETER
    (after its `<LomId>`), with `Channel=16` (macro sentinel), `IsNote=false`, `ControllerMapMode=0`,
    `Lower/UpperRangeNote=-1`, and **`NoteOrController` = the 0-based macro index** (Macro 1→0). NO ids
    (all AutomationTarget/ModulationTarget stay 0; factory non-zero ids are MacroSnapshots/preset-refs,
    unrelated). Confirmed: test Macro1→Gain gave NoteOrController=0; factory "Basic Bass Amp" — all 16
    mapped params carry Channel=16 KeyMidi w/ NoteOrController=macro index; many params can share a macro.
    Default full-range mapping needs NO range edit (param's MidiControllerRange unchanged). Custom/inverted
    ranges = deferred v2 (storage unconfirmed). See spec Section 3 "FINDINGS".
  - **`add_rack_macro_mappings` (Phase B v1): LIVE-VERIFIED 2026-05-29.** Tool + `patch_macro_mappings`
    in `rack_preset_utils.py` (depth-aware `_child_elements` scanner navigates branch→DevicePresets→
    AbletonDevicePreset→Device→device-element→param; injects KeyMidi after `<LomId>`; idempotent replace;
    many-to-one; bad chain/device/param rejected with available-tag listing). Plan:
    `docs/superpowers/plans/2026-05-29-rack-macro-mappings.md`. Offline 307/307.
    Live: cloned "Basic Bass Amp"→MCP MapVerify, mapped Macro 16→chain0/device0(Gate)/Attack via the util,
    loaded onto a scratch track → Live PARSED it cleanly AND `get_rack_macros` showed macro 16 auto-renamed
    "Attack" (Live auto-labels a single-mapped unnamed macro with its target = proof the mapping bound).
    Scratch track + preset cleaned up. Addresses params that are DIRECT children of a (non-rack) device;
    nested rack-in-rack params + custom ranges = future. Shipped as plugin v0.3.0.

## Sample sourcing (#4a) spike findings (2026-06-19, vs Live 12 Suite, AbletonDev)
- Browser lists samples: top-level category "samples" (`query:Samples`), FLAT index of 10447 items, each `{name, uri:"query:Samples#FileId_N", is_loadable}` - NO folders, NO filesystem path exposed by the LOM browser.
- load_audio_clip PRIMARY (A) CONFIRMED: load_browser_item with a sample URI onto an audio track creates a real AUDIO CLIP in the selected slot (is_audio_clip, length 16, looping, warped) - no device added. Slot used = the highlighted slot (default 0).
- load_sample_to_drum_pad PRIMARY (A) CONFIRMED-ish: load_browser_item with a sample URI onto a track holding a Drum Rack adds the sample as a PAD/chain (chain_count 0->1, chain name = sample, contains a sample-player device) - no clip. OPEN: targeting a SPECIFIC pad note needs pad pre-selection (not yet exposed) -> new RS command, OR preset-patch .adg fallback (path-based).
- Factory samples root: <Core Library>/Samples with subfolders Loops/, One Shots/, Multisamples/ (matches classify_sample tokens). User Library: <User Library>/Samples (iCloud).
- KEY: loaders need the browser URI; the browser exposes no path; the FS-walk search returns paths, not URIs. Design RESOLVED by user = HYBRID: keep FS-walk search (paths+classification), add an RS command to resolve a sample name/path -> browser URI so loaders take paths and resolve internally; keep _ensure_local for the preset-patch fallback.

### Task 4.5 live-verify (2026-06-19): RS find_sample_uri + select_drum_pad
- `find_sample_uri` (socket probe, blank set): "3Q_AMD_Clap_21.wav" -> query:Samples#FileId_281815, "3Q_AMD_Full_Drum_Loop_08.wav" -> query:Samples#FileId_281788 (match the spike's browser URIs), nonexistent -> {uri:null, matches:0}. PASS.
- `select_drum_pad`: note 36 + 38 both -> {selected:true}. Full hybrid flow verified: select_drum_pad(4,36) -> resolve clap uri -> load_browser_item landed the clap on PAD 36 (chain 0). PASS. (A back-to-back 2nd load via the raw probe socket hit the probe's recv timeout, leaving an empty pad-38 chain - not an RS defect; load_browser_item is pre-existing.) Scratch track deleted.

### Task 9 live-verify (2026-06-19, Live 12 Suite): all 4 sample tools
Verified end-to-end via subprocess import of the working-tree server (real tool code -> real 9877 connection -> Live):
- search_samples: "kick"/one_shot 442 hits, "loop"/loop 882 hits (user+factory), empty 4625 total; correct source/kind/icloud flags.
- load_audio_clip: "Hihat Closed Loop.aif" (factory) -> real AUDIO CLIP (is_audio_clip=True, kind=loop, loaded=True, uri resolved).
- load_sample_to_drum_pad: "Kick 909 Tune1 g.wav" -> pad 36 (loaded=True).
- populate_drum_rack: 2 one-shots -> pads 38/40, loaded_count=2; rack pads = [Kick 909, Kick Open Hat Combo, Rim Clap ER].
- Scratch tracks self-cleaned (track_count back to baseline).
- Incidental: a few User Library samples are 4-bit WAVs Live can't read; load_audio_clip surfaces that honestly as ok:false (correct, not a bug).
