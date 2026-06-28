import gzip, os
import pytest
from ableton_mcp_max import server

TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"


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
        from ableton_mcp_max import serum_fx_utils as fx
        items = fx.list_fx(tree)
        if items:
            it = items[0]
            # set first param of first fx to its current value (no-op, in range not enforced via catalog here)
            pp = fx.get_fx_params(tree, it["rack"], it["slot"])
            for k, v in pp.items():
                if isinstance(v, float):
                    fx.set_fx_enabled(tree, it["rack"], it["slot"], True)
                    break

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
    assert "xml" in written and len(written["xml"]) > 0
