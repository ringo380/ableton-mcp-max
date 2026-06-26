"""SessionStart orientation for the ableton plugin.

Prints a distilled tool-usage core when a music context is detected
(Ableton Live running, or a project-brief.md in the cwd), plus a pointer
to per-project state files when a project-brief.md is present. Silent otherwise.
"""
import os
import pathlib
import shutil
import subprocess
import sys

CORE = """\
Ableton MCP active. Cardinal rules for driving Live reliably:
- Every tool returns {ok, data|error}; check `ok`, never string-sniff for "Error".
- Re-read state every session: get_session_info + get_track_info first. The open set
  changes between sessions - never carry a track index forward.
- Write-lag: song-level writes (transport/record/loop/tempo/scenes) apply async; the
  returned confirmation is often the pre-write value. Verify with a SEPARATE read. After
  undo/redo, structural reads can be stale for one call - read twice.
- MIDI notes: use the extended API only (add_notes_to_clip / replace_clip_notes /
  modify_clip_notes / remove_clip_notes). Never legacy set_notes/remove_notes (blocking
  modal -> socket timeout). quantize_clip is safe.
- Loading devices HOT-SWAPS: load_instrument_or_effect / load_preset / load_drum_kit
  REPLACE the track's instrument. Experiment on an empty track, delete_device after.
- Device-tool asymmetry: get_automation / set_automation are regular-track only. The device
  param/rack tools (get_device_parameters, set_device_parameter, get_device_info,
  get_rack_macros, set_rack_macro, set_chain_property, set_device_on, delete_device) take
  track_type and reach return/master devices (since PR #24).
- Return/master/group tracks have no .arm; group tracks have no monitoring. Probe optional
  endpoints defensively. No LOM call creates a group track (UI-only).
- undo is GLOBAL (it undoes user hand-edits too).
- "Could not connect to Ableton" right after a restart: just retry while the server
  reconnects. Run /ableton:setup if it persists.
- For deep how-to (mixing, mastering, sound design, arrangement, MIDI, samples, analysis)
  the ableton-* skills auto-load when you start that kind of task.
"""

BRIEF_POINTER = """\
Music project detected. Before acting, read project-brief.md (creative goal),
decisions.md (what's been done), and samples.md (audio palette). Append outcomes to
decisions.md as you work. Run /ableton:init-project to (re)scaffold these.
"""


def build_orientation(brief_exists: bool, live_running: bool) -> str:
    if not brief_exists and not live_running:
        return ""
    out = CORE
    if brief_exists:
        out = out + "\n" + BRIEF_POINTER
    return out


def _live_running() -> bool:
    if shutil.which("pgrep") is None:
        return False
    try:
        return (
            subprocess.run(
                ["pgrep", "-f", "Ableton Live"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    except Exception:
        return False


def main() -> None:
    # ORIENT_PWD is set by orient.sh to preserve the session cwd before
    # uv run --directory changes it to the plugin root.
    cwd = pathlib.Path(os.environ.get("ORIENT_PWD") or os.getcwd())
    brief_exists = (cwd / "project-brief.md").is_file()
    text = build_orientation(brief_exists=brief_exists, live_running=_live_running())
    if text:
        sys.stdout.write(text)


if __name__ == "__main__":
    # A SessionStart hook must never fail the session: swallow any error
    # (e.g. a closed output pipe) so the process always exits cleanly.
    try:
        main()
    except Exception:
        pass
