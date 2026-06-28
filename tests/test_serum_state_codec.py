# tests/test_serum_state_codec.py
import binascii, gzip, re, glob, os
import pytest
from ableton_mcp_max import serum_state_codec as sc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"

def _als_processor_blob(path):
    raw = gzip.open(path, "rb").read()
    txt = raw.decode("utf-8", "replace")
    m = re.search(r"<ProcessorState[^>]*>(.*?)</ProcessorState>", txt, re.S)
    hexonly = re.sub(r"<[^>]+>", "", re.sub(r"\s", "", m.group(1)))
    return binascii.unhexlify(hexonly[: len(hexonly) // 2 * 2])

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_decode_then_encode_noop_is_tree_equal():
    blob = _als_processor_blob(TEST_ALS)
    st = sc.decode(blob)
    assert "FXRack0" in st.tree
    re_blob = sc.encode(st, st.tree)
    st2 = sc.decode(re_blob)
    assert st2.tree == st.tree
    assert st2.meta["hash"] == sc.hashlib.md5(re_blob[re_blob.find(b"\x28\xb5\x2f\xfd"):]).hexdigest()

@pytest.mark.skipif(not glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True),
                    reason="factory presets absent")
def test_all_factory_presets_roundtrip_tree_equal():
    files = glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True)
    for f in files:
        blob = open(f, "rb").read()
        st = sc.decode(blob)
        st2 = sc.decode(sc.encode(st, st.tree))
        assert st2.tree == st.tree, f
