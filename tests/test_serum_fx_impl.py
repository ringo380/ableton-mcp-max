import gzip, os, re
import pytest
from ableton_mcp_max import server
from ableton_mcp_max import serum_state_codec as ssc
from ableton_mcp_max import serum_fx_utils as fxu

TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"


def _state_hex(xml, tag, device_index=0):
    """Re-extract the inner hex of the device_index-th <tag> in xml."""
    opens = list(re.finditer(r"<%s[^>]*>" % tag, xml))
    o = opens[device_index]
    close = xml.index("</%s>" % tag, o.end())
    return xml[o.end():close]


@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_read_impl_lists_fx(tmp_path):
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    res = server._serum_fx_read_impl(
        0, 0,
        save_impl=lambda: {"saved": True},
        read_als=lambda p: xml,
        find_track_span=__import__("ableton_mcp_max.als_automation_utils", fromlist=["x"]).find_track_span,
        resolve_path=lambda: str(TEST_ALS),
        title_fn=lambda: "serum2_idtest")
    assert res["ok"] is True
    assert isinstance(res["fx"], list)


@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_mutate_impl_roundtrips_and_writes(tmp_path):
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    written = {}

    def mutate(catalog, tree):
        # Disable the first FX in rack 0 (writes kParamEnable=0.0 on it).
        fxu.set_fx_enabled(tree, 0, 0, False)

    res = server._serum_fx_mutate_impl(
        0, 0, mutate, reload=False,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: True,
        read_als=lambda p: xml,
        write_als=lambda p, x: written.update(xml=x),
        find_track_span=__import__("ableton_mcp_max.als_automation_utils", fromlist=["x"]).find_track_span,
        resolve_path=lambda: str(TEST_ALS),
        title_fn=lambda: "serum2_idtest")
    assert res["ok"] is True
    out_xml = written.get("xml")
    assert out_xml and len(out_xml) > 0

    # The mutation must round-trip through the written ProcessorState blob:
    # rack 0 slot 0 now carries kParamEnable == 0.0.
    proc_tree = ssc.decode(ssc.from_hex(_state_hex(out_xml, "ProcessorState"))).tree
    pp = fxu.get_fx_params(proc_tree, 0, 0)
    assert pp.get("kParamEnable") == 0.0

    # Processor-only patch: the ControllerState bytes must be identical to source.
    assert _state_hex(out_xml, "ControllerState") == _state_hex(xml, "ControllerState")
