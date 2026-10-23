import os
import xml.etree.ElementTree as ET

import pytest

from ableton_mcp_max.als_automation_utils import (
    SENTINEL_TIME,
    read_als,
    write_als,
    points_to_events,
    build_envelope_xml,
    find_target_after_manual,
    patch_manual,
    find_track_span,
    next_envelope_id,
    next_pointee_id,
    set_next_pointee_id,
    inject_envelope,
)

# Live scratch fixture seeded with user-drawn reference envelopes (see memory
# issue30-arrangement-automation). Real-file tests skip when it's absent.
_FIXTURE = "/private/tmp/autospike_test Project/autospike_reload.als"


# --------------------------------------------------------------------------- #
# Task 1: gzip core
# --------------------------------------------------------------------------- #
def test_write_then_read_roundtrips_unicode(tmp_path):
    xml = '<Ableton><Track name="café — ünïcode"/></Ableton>'
    p = str(tmp_path / "x.als")
    write_als(p, xml)
    assert read_als(p) == xml


@pytest.mark.skipif(not os.path.exists(_FIXTURE), reason="no live fixture")
def test_read_real_als_has_ableton_root():
    assert "<Ableton" in read_als(_FIXTURE)


# --------------------------------------------------------------------------- #
# Task 2: points -> events + envelope builder
# --------------------------------------------------------------------------- #
def test_points_to_events_inserts_sentinel_with_first_value():
    ev = points_to_events([{"time": 0, "value": 0.2}, {"time": 8, "value": 0.9}])
    assert ev[0] == (SENTINEL_TIME, 0.2)
    assert ev[1:] == [(0.0, 0.2), (8.0, 0.9)]


def test_points_to_events_sorts_by_time():
    ev = points_to_events([{"time": 8, "value": 0.9}, {"time": 0, "value": 0.1}])
    assert [t for t, _ in ev] == [SENTINEL_TIME, 0.0, 8.0]
    assert ev[0][1] == 0.1  # sentinel carries the EARLIEST point's value


def test_points_to_events_preserves_duplicate_times():
    ev = points_to_events([{"time": 4, "value": 0.0}, {"time": 4, "value": 1.0}])
    assert ev[1:] == [(4.0, 0.0), (4.0, 1.0)]


def test_points_to_events_clamps_to_range():
    ev = points_to_events([{"time": 0, "value": 5.0}, {"time": 1, "value": -5.0}],
                          value_min=0.0, value_max=1.0)
    assert ev[1:] == [(0.0, 1.0), (1.0, 0.0)]


def test_points_to_events_empty_raises():
    with pytest.raises(ValueError):
        points_to_events([])


def test_build_envelope_xml_wellformed_with_pointee_and_events():
    block = build_envelope_xml("777", [{"time": 0, "value": 0.25},
                                       {"time": 16, "value": 0.75}],
                               env_id=3, first_event_id=5000)
    el = ET.fromstring(block)
    assert el.tag == "AutomationEnvelope"
    assert el.attrib["Id"] == "3"
    pid = el.find("./EnvelopeTarget/PointeeId")
    assert pid.attrib["Value"] == "777"
    floats = el.findall("./Automation/Events/FloatEvent")
    assert len(floats) == 3  # sentinel + 2 points
    assert floats[0].attrib["Time"] == str(SENTINEL_TIME)


def test_build_envelope_xml_floatevents_have_unique_sequential_ids():
    # Live 12 rejects the set as corrupt unless every FloatEvent has an Id.
    block = build_envelope_xml("1", [{"time": 0, "value": 0.1},
                                     {"time": 4, "value": 0.2},
                                     {"time": 8, "value": 0.3}],
                               env_id=0, first_event_id=25987)
    floats = ET.fromstring(block).findall("./Automation/Events/FloatEvent")
    ids = [int(f.attrib["Id"]) for f in floats]      # raises KeyError if missing
    assert ids == [25987, 25988, 25989, 25990]        # sentinel + 3 points
    assert len(set(ids)) == len(ids)


def test_build_envelope_xml_no_scientific_notation():
    block = build_envelope_xml("1", [{"time": 0, "value": 0.0003162277571}],
                               env_id=0, first_event_id=1)
    assert "e-" not in block.lower()


def test_next_pointee_id_reads_and_bumps():
    xml = '<LiveSet><NextPointeeId Value="25987" /></LiveSet>'
    assert next_pointee_id(xml) == 25987
    out = set_next_pointee_id(xml, 25991)
    assert '<NextPointeeId Value="25991" />' in out
    assert next_pointee_id(out) == 25991


def test_next_pointee_id_fallback_to_max_id():
    xml = '<a><AutomationTarget Id="42" /><Foo Id="7" /></a>'
    assert next_pointee_id(xml) == 43
    # no element -> set is a no-op
    assert set_next_pointee_id(xml, 99) == xml


# --------------------------------------------------------------------------- #
# Task: find_target_after_manual (probe targeting) + patch_manual
# --------------------------------------------------------------------------- #
_SYNTH = (
    '<Param><Manual Value="0.111" />'
    '<AutomationTarget Id="100"><LockEnvelope Value="0" /></AutomationTarget>'
    '<ModulationTarget Id="101" /></Param>'
    '<Param><Manual Value="0.873421" />'
    '<MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange>'
    '<AutomationTarget Id="200" /></Param>'
    '<On><Manual Value="true" /><AutomationTarget Id="300" /></On>'
)


def test_find_target_after_manual_returns_next_automation_target():
    info = find_target_after_manual(_SYNTH, 0.873421)
    assert info["pointee_id"] == "200"
    assert info["manual_literal"] == '<Manual Value="0.873421" />'


def test_find_target_after_manual_skips_boolean_manual():
    # 'true' isn't a float -> no crash; a distinctive value still resolves.
    info = find_target_after_manual(_SYNTH, 0.111)
    assert info["pointee_id"] == "100"


def test_find_target_after_manual_non_unique_raises():
    dup = ('<a><Manual Value="0.5" /><AutomationTarget Id="1" /></a>'
           '<b><Manual Value="0.5" /><AutomationTarget Id="2" /></b>')
    with pytest.raises(ValueError):
        find_target_after_manual(dup, 0.5)


def test_find_target_after_manual_no_match_raises():
    with pytest.raises(ValueError):
        find_target_after_manual(_SYNTH, 0.42)


def test_patch_manual_rewrites_unique_literal():
    out = patch_manual(_SYNTH, '<Manual Value="0.873421" />', 0.25)
    assert '<Manual Value="0.25" />' in out
    assert '<Manual Value="0.873421" />' not in out


def test_patch_manual_clamps():
    out = patch_manual(_SYNTH, '<Manual Value="0.873421" />', 5.0,
                       value_min=0.0, value_max=1.0)
    assert '<Manual Value="1" />' in out


def test_patch_manual_non_unique_raises():
    dup = '<Manual Value="0.5" /><Manual Value="0.5" />'
    with pytest.raises(ValueError):
        patch_manual(dup, '<Manual Value="0.5" />', 0.1)


# --------------------------------------------------------------------------- #
# Task: track span + envelope injection
# --------------------------------------------------------------------------- #
def _two_track_xml(env0="<Envelopes />", env1="<Envelopes />"):
    track = (
        '<MidiTrack Id="%d" SelectedToolPanel="2">'
        '<AutomationEnvelopes>%s</AutomationEnvelopes>'
        '<DeviceChain/></MidiTrack>'
    )
    return ('<Tracks>' + (track % (8, env0)) + (track % (9, env1)) + '</Tracks>')


def test_find_track_span_handles_extra_attrs():
    xml = _two_track_xml()
    s, e = find_track_span(xml, 0)
    assert xml[s:e].startswith('<MidiTrack Id="8"')
    assert xml[s:e].endswith("</MidiTrack>")
    s1, e1 = find_track_span(xml, 1)
    assert 'Id="9"' in xml[s1:e1]


def test_find_track_span_counts_group_tracks_like_the_lom():
    # song.tracks = [GroupTrack, AudioTrack (in group), MidiTrack]; returns excluded.
    xml = ('<Tracks><GroupTrack Id="1"><DeviceChain/></GroupTrack>'
           '<AudioTrack Id="2"><DeviceChain/></AudioTrack>'
           '<MidiTrack Id="3"><DeviceChain/></MidiTrack>'
           '<ReturnTrack Id="4"><DeviceChain/></ReturnTrack></Tracks>')
    s, e = find_track_span(xml, 0)
    assert xml[s:e].startswith('<GroupTrack Id="1"')
    assert xml[s:e].endswith("</GroupTrack>")
    s, e = find_track_span(xml, 2)
    assert xml[s:e].startswith('<MidiTrack Id="3"')
    with pytest.raises(ValueError):
        find_track_span(xml, 3)


def test_find_track_span_out_of_range_raises():
    with pytest.raises(ValueError):
        find_track_span(_two_track_xml(), 5)


def test_next_envelope_id():
    assert next_envelope_id("<Envelopes></Envelopes>") == 0
    assert next_envelope_id('<AutomationEnvelope Id="0"><AutomationEnvelope Id="4">') == 5


def test_inject_into_self_closing_envelopes():
    xml = _two_track_xml()
    out = inject_envelope(
        xml, 0, "555",
        lambda eid: build_envelope_xml("555", [{"time": 0, "value": 0.5}], eid, first_event_id=1))
    s, e = find_track_span(out, 0)
    assert '<PointeeId Value="555" />' in out[s:e]
    # second track untouched
    s1, e1 = find_track_span(out, 1)
    assert "<Envelopes />" in out[s1:e1]


def test_inject_targets_correct_track():
    xml = _two_track_xml()
    out = inject_envelope(
        xml, 1, "999",
        lambda eid: build_envelope_xml("999", [{"time": 0, "value": 0.5}], eid, first_event_id=1))
    s0, e0 = find_track_span(out, 0)
    assert "999" not in out[s0:e0]
    s1, e1 = find_track_span(out, 1)
    assert '<PointeeId Value="999" />' in out[s1:e1]


def test_inject_second_pointee_appends_with_next_id():
    xml = _two_track_xml()
    out = inject_envelope(
        xml, 0, "111",
        lambda eid: build_envelope_xml("111", [{"time": 0, "value": 0.1}], eid, first_event_id=1))
    out = inject_envelope(
        out, 0, "222",
        lambda eid: build_envelope_xml("222", [{"time": 0, "value": 0.2}], eid, first_event_id=1))
    s, e = find_track_span(out, 0)
    seg = out[s:e]
    assert '<AutomationEnvelope Id="0">' in seg
    assert '<AutomationEnvelope Id="1">' in seg
    assert seg.count("<AutomationEnvelope ") == 2


def test_inject_replace_swaps_existing_pointee():
    xml = _two_track_xml()
    out = inject_envelope(
        xml, 0, "111",
        lambda eid: build_envelope_xml("111", [{"time": 0, "value": 0.1}], eid, first_event_id=1))
    out = inject_envelope(
        out, 0, "111",
        lambda eid: build_envelope_xml("111", [{"time": 0, "value": 0.9},
                                               {"time": 4, "value": 0.3}], eid, first_event_id=1),
        replace=True)
    s, e = find_track_span(out, 0)
    seg = out[s:e]
    assert seg.count('<PointeeId Value="111" />') == 1
    # the new envelope (3 FloatEvents: sentinel + 2) replaced the old (2)
    env = seg[seg.find("<AutomationEnvelope"):]
    assert env.count("<FloatEvent ") == 3


def test_injected_region_reparses():
    xml = _two_track_xml()
    out = inject_envelope(
        xml, 0, "123",
        lambda eid: build_envelope_xml("123", [{"time": 0, "value": 0.5},
                                               {"time": 16, "value": 1.0}], eid, first_event_id=1))
    s, e = find_track_span(out, 0)
    ET.fromstring(out[s:e])  # must be well-formed


# --------------------------------------------------------------------------- #
# Real-file end-to-end round-trip (gated)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.path.exists(_FIXTURE), reason="no live fixture")
def test_real_file_resolve_inject_roundtrip(tmp_path):
    xml = read_als(_FIXTURE)
    # The fixture's track 1 holds the MACRO reference envelope (PointeeId 22754).
    # Re-inject a fresh 3-point envelope for that PointeeId and round-trip.
    out = inject_envelope(
        xml, 1, "22754",
        lambda eid: build_envelope_xml("22754",
                                       [{"time": 0, "value": 10},
                                        {"time": 8, "value": 90},
                                        {"time": 16, "value": 50}], eid, first_event_id=1),
        replace=True)
    p = str(tmp_path / "rt.als")
    write_als(p, out)
    back = read_als(p)
    s, e = find_track_span(back, 1)
    seg = back[s:e]
    assert seg.count('<PointeeId Value="22754" />') == 1
    ET.fromstring(back[back.find("<Tracks"):back.rfind("</Tracks>") + len("</Tracks>")])
