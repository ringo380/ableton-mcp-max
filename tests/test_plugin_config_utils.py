"""Offline tests for the plugin Configure-slot XML encoder.

These exercise the pure logic that fills empty <PluginFloatParameter> slots in a
plugin device's <ParameterList> so the params become live LOM DeviceParameters
after reload (the Configure-list backdoor). No Live / no network.
"""
from ableton_mcp_max import plugin_config_utils as pcu


# One empty slot, real Ableton shape (multi-line + tabs, like a true .als).
EMPTY = (
    '<PluginFloatParameter Id="0">\n'
    '\t<ParameterName Value="" />\n'
    '\t<ParameterId Value="-1" />\n'
    '\t<ParameterIdFlankBool Value="false" />\n'
    '\t<VisualIndex Value="1073741823" />\n'
    '\t<ParameterValue>\n'
    '\t\t<LomId Value="0" />\n'
    '\t\t<Manual Value="0.1234567687" />\n'
    '\t\t<MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange>\n'
    '\t\t<AutomationTarget Id="100"><LockEnvelope Value="0" /></AutomationTarget>\n'
    '\t\t<ModulationTarget Id="101"><LockEnvelope Value="0" /></ModulationTarget>\n'
    '\t</ParameterValue>\n'
    '\t<LastUserRange><First Value="Invalid" /><Last Value="Invalid" /></LastUserRange>\n'
    '\t<LastInternalRange><First Value="0" /><Last Value="1" /></LastInternalRange>\n'
    '</PluginFloatParameter>'
)


def test_find_empty_slots():
    assert pcu.find_empty_slots(EMPTY) == [0]


def test_find_empty_slots_skips_filled():
    filled = pcu.build_slot(0, 2000003, "Filter 1 Freq", "1547.45", 0, 200, 201)
    assert pcu.find_empty_slots(filled) == []


def test_count_slots():
    assert pcu.count_slots(EMPTY + EMPTY) == 2


def test_max_target_id():
    assert pcu.max_target_id(EMPTY) == 101


def test_build_slot_sets_fields():
    blk = pcu.build_slot(7, 2000003, "Filter 1 Freq", "1547.45", 0, 200, 201)
    assert 'Id="7"' in blk
    assert '<ParameterId Value="2000003" />' in blk
    assert '<ParameterName Value="Filter 1 Freq" />' in blk
    assert '<Manual Value="1547.45" />' in blk
    assert '<VisualIndex Value="0" />' in blk
    assert '<AutomationTarget Id="200">' in blk
    assert '<ModulationTarget Id="201">' in blk
    # the result must itself be detectable as a non-empty slot
    assert pcu.find_empty_slots(blk) == []


def test_build_slot_escapes_name():
    blk = pcu.build_slot(0, 1, "A & B <x>", "0.5", 0, 1, 2)
    assert '<ParameterName Value="A &amp; B &lt;x&gt;" />' in blk


def test_fill_slots_fills_one():
    params = [{"param_id": 2000003, "name": "Filter 1 Freq", "manual": "1547.45", "visual_index": 0}]
    out, dropped = pcu.fill_slots(EMPTY, params, start_target_id=200)
    assert '<ParameterId Value="2000003" />' in out
    assert '<ParameterId Value="-1" />' not in out
    assert dropped == 0


def test_fill_slots_reports_overflow():
    params = [
        {"param_id": 2000003, "name": "A", "manual": "0.1", "visual_index": 0},
        {"param_id": 2000004, "name": "B", "manual": "0.2", "visual_index": 1},
        {"param_id": 2000005, "name": "C", "manual": "0.3", "visual_index": 2},
    ]
    # only one empty slot available -> two dropped
    out, dropped = pcu.fill_slots(EMPTY, params, start_target_id=200)
    assert dropped == 2
    assert '<ParameterId Value="2000003" />' in out


def test_fill_slots_allocates_unique_target_ids():
    pool = EMPTY.replace('Id="0"', 'Id="0"', 1) + "\n" + EMPTY.replace('Id="0"', 'Id="1"')
    params = [
        {"param_id": 2000003, "name": "A", "manual": "0.1", "visual_index": 0},
        {"param_id": 2000004, "name": "B", "manual": "0.2", "visual_index": 1},
    ]
    out, dropped = pcu.fill_slots(pool, params, start_target_id=200)
    assert dropped == 0
    # ids allocated sequentially: 200/201 for slot A, 202/203 for slot B
    assert '<AutomationTarget Id="200">' in out
    assert '<ModulationTarget Id="201">' in out
    assert '<AutomationTarget Id="202">' in out
    assert '<ModulationTarget Id="203">' in out


def test_bump_next_pointee_id():
    doc = '<Foo><NextPointeeId Value="22846" /><Bar /></Foo>'
    out, start = pcu.bump_next_pointee_id(doc, count=1)
    # one slot needs two ids; counter advances by 2 and the first allocatable id is the old value
    assert start == 22846
    assert '<NextPointeeId Value="22848" />' in out


def test_bump_next_pointee_id_multi():
    doc = '<Foo><NextPointeeId Value="500" /></Foo>'
    out, start = pcu.bump_next_pointee_id(doc, count=3)
    assert start == 500
    assert '<NextPointeeId Value="506" />' in out  # 500 + 2*3


# --- locate_param_list (device navigation) --------------------------------

def _track(devices_inner, plist='<ParameterList><PluginFloatParameter Id="0" /></ParameterList>'):
    """A synthetic track whose main <Devices> holds `devices_inner`."""
    return (
        '<MidiTrack Id="9">'
        '<Mixer><Sends><ParameterList>MIXER_PLIST</ParameterList></Sends></Mixer>'
        '<DeviceChain><Devices>%s</Devices></DeviceChain>'
        '</MidiTrack>'
    ) % devices_inner


def test_locate_param_list_first_device():
    plist = '<ParameterList><Slot Id="7" /></ParameterList>'
    xml = _track('<PluginDevice Id="0"><X />%s</PluginDevice>' % plist)
    s, e = pcu.locate_param_list(xml, 0, len(xml), 0)
    # Must select the PLUGIN's ParameterList, not the earlier mixer-sends one.
    assert xml[s:e] == plist
    assert "MIXER_PLIST" not in xml[s:e]


def test_locate_param_list_second_device_skips_native():
    plist = '<ParameterList><Slot Id="7" /></ParameterList>'
    inner = ('<Operator Id="0"><ParameterList>NATIVE</ParameterList></Operator>'
             '<PluginDevice Id="1"><Y />%s</PluginDevice>') % plist
    xml = _track(inner)
    s, e = pcu.locate_param_list(xml, 0, len(xml), 1)
    assert xml[s:e] == plist


def test_locate_param_list_rejects_non_plugin():
    xml = _track('<Operator Id="0"><ParameterList>N</ParameterList></Operator>')
    try:
        pcu.locate_param_list(xml, 0, len(xml), 0)
        assert False, "expected ValueError"
    except ValueError as err:
        assert "not a VST/AU plugin" in str(err)


def test_locate_param_list_index_out_of_range():
    xml = _track('<PluginDevice Id="0"><ParameterList>P</ParameterList></PluginDevice>')
    try:
        pcu.locate_param_list(xml, 0, len(xml), 5)
        assert False, "expected ValueError"
    except ValueError as err:
        assert "out of range" in str(err)


def test_locate_param_list_ignores_nested_rack_devices():
    # An instrument rack: its chain holds a nested <Devices> with another plugin.
    # device 0 is the rack (GroupDevice); its ParameterList is the macros list.
    nested = ('<InstrumentGroupDevice Id="0">'
              '<ParameterList>MACROS</ParameterList>'
              '<Branches><Branch><DeviceChain><Devices>'
              '<PluginDevice Id="1"><ParameterList>INNER</ParameterList></PluginDevice>'
              '</Devices></DeviceChain></Branch></Branches>'
              '</InstrumentGroupDevice>')
    xml = _track(nested)
    # device 0 is the rack -> not a plugin (rejected, correct: macros aren't VST params)
    try:
        pcu.locate_param_list(xml, 0, len(xml), 0)
        assert False
    except ValueError as err:
        assert "not a VST/AU plugin" in str(err)
    # there is exactly one top-level device (the rack); index 1 is out of range,
    # proving the nested inner plugin is NOT counted as a sibling.
    try:
        pcu.locate_param_list(xml, 0, len(xml), 1)
        assert False
    except ValueError as err:
        assert "out of range" in str(err)
