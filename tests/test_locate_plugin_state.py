import gzip, os, re
import pytest
from ableton_mcp_max import plugin_config_utils as pcu
from ableton_mcp_max import als_automation_utils as als

TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_locate_and_identify_serum_state():
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    ts, te = als.find_track_span(xml, 0)
    spans = pcu.locate_plugin_state(xml, ts, te, 0)
    for key in ("processor", "controller"):
        s, e = spans[key]
        inner = xml[s:e]
        assert pcu.is_serum_state(inner)

def test_missing_device_raises():
    xml = "<Tracks><MidiTrack></MidiTrack></Tracks>"
    with pytest.raises(ValueError):
        pcu.locate_plugin_state(xml, 0, len(xml), 0)
