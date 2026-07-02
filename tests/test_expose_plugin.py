"""Tests for the expose_plugin_parameters orchestration (_expose_plugin_impl).
All OS/UI/connection/IO seams are stubbed so the save -> patch -> reload
choreography runs without a real Live."""
import pytest

from ableton_mcp_max import server


def _empty_slot(slot_id):
    return (
        '<PluginFloatParameter Id="%d">'
        '<ParameterName Value="" />'
        '<ParameterId Value="-1" />'
        '<VisualIndex Value="1073741823" />'
        '<ParameterValue>'
        '<AutomationTarget Id="1"><LockEnvelope Value="0" /></AutomationTarget>'
        '<ModulationTarget Id="2"><LockEnvelope Value="0" /></ModulationTarget>'
        '</ParameterValue>'
        '</PluginFloatParameter>'
    ) % slot_id


def _doc(n_empty=2, next_id=1000):
    slots = "".join(_empty_slot(i) for i in range(n_empty))
    return (
        '<Ableton><NextPointeeId Value="%d" />'
        '<Tracks><MidiTrack Id="1">'
        '<DeviceChain><Devices>'
        '<PluginDevice Id="0"><ParameterList>%s</ParameterList></PluginDevice>'
        '</Devices></DeviceChain>'
        '</MidiTrack></Tracks></Ableton>'
    ) % (next_id, slots)


def _run(doc, params, **over):
    store = {"/x.als": doc}
    kw = dict(
        track_index=0, device_index=0, track_type="regular", params=params,
        manual="0.5", reload=True,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: {"reloaded": True},
        read_als=lambda p: store[p],
        write_als=lambda p, x: store.__setitem__(p, x),
        title_fn=lambda: "myset",
        resolve_path=lambda: "/x.als",
    )
    kw.update(over)
    data = server._expose_plugin_impl(**kw)
    return data, store


PARAMS = [
    {"param_id": 2000003, "name": "Filter 1 Freq"},
    {"param_id": 7000000, "name": "Macro 1"},
]


def test_fills_empty_slots_and_reports_counts():
    data, store = _run(_doc(n_empty=2), PARAMS)
    assert data["exposed_count"] == 2
    assert data["dropped_count"] == 0
    assert data["reloaded"] is True
    assert data["method"] == "live_set"
    out = store["/x.als"]
    assert '<ParameterId Value="2000003" />' in out
    assert '<ParameterName Value="Filter 1 Freq" />' in out
    assert '<ParameterName Value="Macro 1" />' in out
    # NextPointeeId advanced by 2 per filled slot (2 slots -> +4).
    assert '<NextPointeeId Value="1004" />' in out
    # both empty sentinels are gone.
    assert '<ParameterId Value="-1" />' not in out


def test_overflow_drops_extra_params():
    data, store = _run(_doc(n_empty=1), PARAMS)
    assert data["exposed_count"] == 1
    assert data["dropped_count"] == 1
    # only the first param was written; NextPointeeId advanced by 2 (one slot).
    assert '<ParameterId Value="2000003" />' in store["/x.als"]
    assert '<NextPointeeId Value="1002" />' in store["/x.als"]


def test_no_empty_slots_returns_error_without_writing():
    written = {}
    data, store = _run(_doc(n_empty=0), PARAMS,
                       write_als=lambda p, x: written.__setitem__(p, x))
    assert data["exposed_count"] == 0
    assert data["dropped_count"] == len(PARAMS)
    assert "no empty Configure slots" in data["error"]
    assert not written  # nothing written when nothing fits


def test_untitled_set_errors():
    with pytest.raises(ValueError, match="untitled"):
        _run(_doc(), PARAMS, title_fn=lambda: "")


def test_invalid_track_type_errors():
    with pytest.raises(ValueError, match="track_type must be regular, return, or master"):
        _run(_doc(), PARAMS, track_type="bogus")


def test_save_failure_short_circuits():
    data, store = _run(_doc(), PARAMS, save_impl=lambda: {"saved": False})
    assert data["exposed_count"] == 0
    assert "save_set failed" in data["error"]


def test_visual_index_continues_after_existing_filled_slots():
    # one pre-filled slot (id 2000007) + one empty -> the new param gets VisualIndex 1.
    filled = (
        '<PluginFloatParameter Id="9">'
        '<ParameterName Value="Filter 1 Stereo" />'
        '<ParameterId Value="2000007" />'
        '<VisualIndex Value="0" />'
        '</PluginFloatParameter>'
    )
    doc = (
        '<Ableton><NextPointeeId Value="1000" />'
        '<Tracks><MidiTrack Id="1"><DeviceChain><Devices>'
        '<PluginDevice Id="0"><ParameterList>%s%s</ParameterList></PluginDevice>'
        '</Devices></DeviceChain></MidiTrack></Tracks></Ableton>'
    ) % (filled, _empty_slot(0))
    data, store = _run(doc, [PARAMS[0]])
    assert data["exposed_count"] == 1
    assert '<VisualIndex Value="1" />' in store["/x.als"]
