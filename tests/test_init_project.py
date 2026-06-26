import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "init_project",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "init_project.py",
)
init_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_project)


def test_scaffold_creates_all_artifacts(tmp_path):
    res = init_project.scaffold(tmp_path)
    assert (tmp_path / "project-brief.md").is_file()
    assert (tmp_path / "decisions.md").is_file()
    assert (tmp_path / "samples.md").is_file()
    assert (tmp_path / ".claude" / "plans" / "_template.md").is_file()
    assert set(res["skipped"]) == set()
    assert "project-brief.md" in res["created"]


def test_scaffold_no_clobber(tmp_path):
    (tmp_path / "project-brief.md").write_text("MY NOTES", encoding="utf-8")
    res = init_project.scaffold(tmp_path)
    assert (tmp_path / "project-brief.md").read_text(encoding="utf-8") == "MY NOTES"
    assert "project-brief.md" in res["skipped"]
    assert "project-brief.md" not in res["created"]
