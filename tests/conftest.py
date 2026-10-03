"""Shared test setup.

The server picks its OS layer at import (server.IS_WINDOWS). The UI/process
tests were written against the macOS flow and patch its seams (_osa,
_live_app_and_pid, ...), so by default every test runs the macOS branch even on
a Windows machine - otherwise an unpatched Windows primitive could reach a REAL
running Live (post WM_CLOSE to it, open dialogs). Windows-flow tests opt in
with the `windows_flow` fixture and must patch server._win themselves.
"""
import pytest

from ableton_mcp_max import server


@pytest.fixture(autouse=True)
def _macos_flow_by_default(monkeypatch):
    monkeypatch.setattr(server, "IS_WINDOWS", False)
    monkeypatch.setattr(server, "_SAVE_WINDOW", "Save")
    monkeypatch.setattr(server, "_export_ui", server._ExportUI())


@pytest.fixture
def windows_flow(monkeypatch):
    monkeypatch.setattr(server, "IS_WINDOWS", True)
    monkeypatch.setattr(server, "_SAVE_WINDOW", "Save Audio File As:")
