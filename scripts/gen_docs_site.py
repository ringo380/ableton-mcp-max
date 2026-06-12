#!/usr/bin/env python3
"""Generate the Jekyll docs site (docs/) from the @mcp.tool() definitions in server.py.

Reliable enumeration uses the `ast` module (NOT regex) - tool signatures span
multiple lines, so a `\\([^)]*\\)` regex matches nothing and yields empty docstrings.

Run from the repo root:  python3 scripts/gen_docs_site.py
Regenerates: docs/tools/index.md and docs/tools/<category>.md
Does NOT touch hand-authored files (docs/_config.yml, docs/index.md, docs/Gemfile,
docs/_sass/...).
"""
import ast
import os
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "ableton_mcp_max", "server.py")
TOOLS_DIR = os.path.join(REPO, "docs", "tools")

# Ordered category map. Every tool name MUST appear exactly once (asserted below).
CATEGORIES = [
    ("session-view", "Session & View", "Read the live set, move the selection, and steer what Live shows on screen.", [
        "get_session_info", "get_view_selection", "set_selected_track", "set_selected_scene",
        "set_detail_clip", "set_highlighted_clip_slot",
    ]),
    ("tracks", "Tracks", "Create, name, fold, duplicate, and delete tracks - plus global undo/redo.", [
        "get_track_info", "set_track_name", "set_track_fold", "create_midi_track", "create_audio_track",
        "create_return_track", "delete_track", "delete_return_track", "duplicate_track", "undo", "redo",
    ]),
    ("clips", "Clips", "Create and manage session clips: properties, loop, quantize, launch, and stop.", [
        "create_clip", "set_clip_name", "get_clip_info", "set_clip_property", "set_clip_loop",
        "quantize_clip", "duplicate_clip", "delete_clip", "fire_clip", "stop_clip",
        "set_clip_trigger_quantization",
    ]),
    ("midi-notes", "MIDI Notes", "Read and edit notes inside MIDI clips via the Live 11 extended note API.", [
        "add_notes_to_clip", "get_clip_notes", "replace_clip_notes", "remove_clip_notes", "modify_clip_notes",
    ]),
    ("devices-racks", "Devices & Racks", "Inspect and drive devices, rack macros, and chains; load instruments and effects.", [
        "get_device_parameters", "set_device_parameter", "get_device_info", "delete_device", "set_device_on",
        "get_rack_macros", "set_rack_macro", "get_rack_chains", "set_chain_property", "load_instrument_or_effect",
    ]),
    ("mixer-routing", "Mixer & Routing", "Volume, pan, sends, and input/output routing for every track type.", [
        "get_mixer", "set_mixer_property", "get_routing", "set_routing",
    ]),
    ("scenes", "Scenes", "Create, launch, rename, and capture scenes in the Session view.", [
        "get_scenes", "fire_scene", "create_scene", "delete_scene", "duplicate_scene", "set_scene_name",
        "set_scene_property", "capture_and_insert_scene",
    ]),
    ("transport", "Transport & Playback", "Tempo, groove, metronome, recording, punch, and the playhead.", [
        "set_tempo", "start_playback", "stop_playback", "continue_playback", "get_transport",
        "set_groove_amount", "set_swing_amount", "set_midi_recording_quantization", "set_nudge",
        "capture_midi", "trigger_session_record", "stop_all_clips", "tap_tempo", "set_metronome",
        "set_arrangement_record", "set_session_record", "set_punch", "set_song_position", "jump_by",
    ]),
    ("arrangement", "Arrangement & Cues", "Cue points, the arrangement loop, and arrangement-timeline clips.", [
        "get_cue_points", "create_cue_point", "delete_cue_point", "jump_to_cue", "set_arrangement_loop",
        "back_to_arrangement", "get_arrangement_clips", "duplicate_clip_to_arrangement", "delete_arrangement_clip",
    ]),
    ("automation", "Automation", "Read and write clip automation envelopes for any automatable parameter.", [
        "get_automation", "set_automation", "create_automation_envelope", "clear_automation",
        "clear_all_automation", "re_enable_automation",
    ]),
    ("browser-presets", "Browser & Presets", "Walk the browser, load presets and drum kits, and generate presets via the preset-XML backdoor.", [
        "get_browser_tree", "get_browser_items_at_path", "load_drum_kit", "list_device_presets", "load_preset",
        "list_wavetable_tables", "create_wavetable_preset", "create_simpler_instrument", "inspect_rack_preset",
        "clone_rack", "rename_rack_macros", "set_rack_zones", "add_rack_macro_mappings",
    ]),
    ("listeners", "Listeners", "Subscribe to real-time Live Object Model changes and poll for events.", [
        "register_listener", "poll_changes", "unregister_listener", "list_listeners",
    ]),
    ("batch", "Batch & Transactions", "Collapse several mutations into a single atomic Live task / socket round-trip.", [
        "batch",
    ]),
    ("analysis", "Analysis", "Inspect the open set against best-practice rulesets and surface findings by domain.", [
        "analyze_set",
    ]),
    ("metering", "Metering (Audio Tap)", "Read master-bus loudness/true-peak from the MCP Audio Tap Max-for-Live device.", [
        "get_audio_tap_status",
        "reset_meter",
        "read_meter",
        "measure_loudness",
    ]),
]

SKIP_PARAMS = {"self", "ctx", "context"}


def is_tool(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "tool":
            return True
    return False


def signature(fn):
    args = fn.args
    parts = []
    defaults = args.defaults
    pos = args.posonlyargs + args.args
    n_def = len(defaults)
    offset = len(pos) - n_def
    for i, a in enumerate(pos):
        if a.arg in SKIP_PARAMS:
            continue
        s = a.arg
        if a.annotation is not None:
            s += ": " + ast.unparse(a.annotation)
        di = i - offset
        if di >= 0:
            s += " = " + ast.unparse(defaults[di])
        parts.append(s)
    for i, a in enumerate(args.kwonlyargs):
        if a.arg in SKIP_PARAMS:
            continue
        s = a.arg
        if a.annotation is not None:
            s += ": " + ast.unparse(a.annotation)
        if args.kw_defaults[i] is not None:
            s += " = " + ast.unparse(args.kw_defaults[i])
        parts.append(s)
    return parts


def collect():
    tree = ast.parse(open(SERVER).read())
    tools = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_tool(node):
            tools[node.name] = {
                "name": node.name,
                "params": signature(node),
                "doc": ast.get_docstring(node) or "",
            }
    return tools


def render_category(slug, title, blurb, names, tools, order):
    lines = [
        "---",
        "layout: default",
        f"title: {title}",
        "parent: Tools",
        f"nav_order: {order}",
        "---",
        "",
        f"# {title}",
        "{: .no_toc }",
        "",
        blurb,
        "",
        "<details open markdown=\"block\">",
        "  <summary>Tools on this page</summary>",
        "  {: .text-delta }",
        "1. TOC",
        "{:toc}",
        "</details>",
        "",
        "---",
        "",
    ]
    for name in names:
        t = tools[name]
        sig = f"{name}(" + ", ".join(t["params"]) + ")"
        lines.append(f"## {name}")
        lines.append("")
        lines.append("```python")
        # wrap long signatures for readability
        if len(sig) > 88:
            inner = ",\n    ".join(t["params"])
            lines.append(f"{name}(\n    {inner},\n)")
        else:
            lines.append(sig)
        lines.append("```")
        lines.append("")
        doc = textwrap.dedent(t["doc"]).strip()
        lines.append(doc if doc else "_No description._")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_index(total):
    lines = [
        "---",
        "layout: default",
        "title: Tools",
        "nav_order: 2",
        "has_children: true",
        "---",
        "",
        "# Tool Reference",
        "",
        f"All **{total} tools** exposed by the `ableton` MCP, grouped by area. Pick a category:",
        "",
    ]
    for slug, title, blurb, names in [(c[0], c[1], c[2], c[3]) for c in CATEGORIES]:
        lines.append(f"## [{title}](./{slug}.html)")
        lines.append("")
        lines.append(f"{blurb}")
        lines.append("")
        lines.append(", ".join(f"`{n}`" for n in names))
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    tools = collect()
    mapped = [n for c in CATEGORIES for n in c[3]]
    missing = set(tools) - set(mapped)
    extra = set(mapped) - set(tools)
    assert not missing, f"Tools not categorized: {sorted(missing)}"
    assert not extra, f"Categorized names that don't exist: {sorted(extra)}"
    assert len(mapped) == len(set(mapped)), "Duplicate tool in category map"
    os.makedirs(TOOLS_DIR, exist_ok=True)
    open(os.path.join(TOOLS_DIR, "index.md"), "w").write(render_index(len(tools)))
    for i, (slug, title, blurb, names) in enumerate(CATEGORIES, start=1):
        path = os.path.join(TOOLS_DIR, f"{slug}.md")
        open(path, "w").write(render_category(slug, title, blurb, names, tools, i))
    print(f"Generated {len(tools)} tools across {len(CATEGORIES)} categories into docs/tools/")


if __name__ == "__main__":
    main()
