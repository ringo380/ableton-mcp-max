import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "orient_hook",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "orient_hook.py",
)
orient_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orient_hook)


def test_silent_when_no_music_context():
    assert orient_hook.build_orientation(brief_exists=False, live_running=False) == ""


def test_core_printed_when_live_running():
    out = orient_hook.build_orientation(brief_exists=False, live_running=True)
    assert "extended" in out.lower()          # MIDI extended-API rule present
    assert "track_type" in out                # device-tool asymmetry present
    assert "project-brief.md" not in out      # no pointer without a brief


def test_brief_pointer_appended_when_brief_exists():
    out = orient_hook.build_orientation(brief_exists=True, live_running=False)
    assert "project-brief.md" in out
    assert "decisions.md" in out
    assert "samples.md" in out
