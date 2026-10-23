import os
import pytest
from ableton_mcp_max import ozone_state_utils as osu

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ozone_processor_state.bin")
BLOB = open(FIXTURE, "rb").read()


def test_decode_reads_header_and_tree():
    st = osu.decode(BLOB)
    assert st.version == 4
    assert set(st.tree.keys()) >= {"Context State", "DSP State"}
    elems = st.tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    assert elems["Maximizer"]["Value"]["Character"]["Value"] == 2


def test_decode_rejects_bad_magic():
    with pytest.raises(ValueError):
        osu.decode(b"NOPE" + BLOB[4:])


def test_decode_rejects_rawlen_mismatch():
    import struct
    bad = BLOB[:12] + struct.pack("<I", 999) + BLOB[16:]
    with pytest.raises(ValueError):
        osu.decode(bad)


def test_encode_roundtrips_tree_and_header():
    st = osu.decode(BLOB)
    blob2 = osu.encode(st, st.tree)
    st2 = osu.decode(blob2)
    assert st2.tree == st.tree
    # header field3 == 4 + len(zlib payload); raw_len == len(json bytes)
    import struct, zlib
    field3 = struct.unpack("<I", blob2[8:12])[0]
    raw_len = struct.unpack("<I", blob2[12:16])[0]
    assert field3 == 4 + len(blob2[16:])
    assert raw_len == len(zlib.decompress(blob2[16:]))


def test_hex_roundtrip_and_is_ozone_state():
    h = osu.to_hex(BLOB)
    assert osu.from_hex(h) == BLOB
    assert osu.is_ozone_state(h) is True
    assert osu.is_ozone_state("DEADBEEF") is False


def _tree():
    return osu.decode(BLOB).tree


def test_module_leaves_and_get_param():
    tree = _tree()
    leaves = osu.module_leaves(tree, "Maximizer")
    assert leaves["Character"] == {"type": "Float", "value": 2}
    assert leaves["Mode"]["type"] == "UInt"
    assert osu.get_param(tree, "Dynamics", "Sidechain HPF") == {"type": "Float", "value": 200}
    with pytest.raises(ValueError):
        osu.module_leaves(tree, "NoSuchModule")


def test_set_param_coerces_by_type():
    tree = _tree()
    assert osu.set_param(tree, "Maximizer", "Target Loudness [dB]", -9) == -9.0
    assert osu.get_param(tree, "Maximizer", "Target Loudness [dB]")["value"] == -9.0
    assert osu.set_param(tree, "Global", "Global Bypass", 1) is True
    assert osu.get_param(tree, "Global", "Global Bypass")["value"] is True
    assert osu.set_param(tree, "Maximizer", "Mode", 2) == 2  # UInt


def test_set_param_rejects_bad_input():
    tree = _tree()
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "NoParam", 1)          # unknown param
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Element Name", "x")   # String unsupported
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Mode", -1)            # UInt negative
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Character", True)     # bool into Float


def test_apply_changes_reports_applied_and_skipped():
    tree = _tree()
    applied, skipped = osu.apply_changes(tree, {
        "Maximizer": {"Target Loudness [dB]": -8.0, "NoParam": 1},
        "Ghost": {"x": 1},
    })
    assert {"module": "Maximizer", "param": "Target Loudness [dB]", "value": -8.0} in applied
    assert osu.get_param(tree, "Maximizer", "Target Loudness [dB]")["value"] == -8.0
    reasons = {(s["module"], s["param"]): s["reason"] for s in skipped}
    assert reasons[("Maximizer", "NoParam")] == "unknown param"
    assert reasons[("Ghost", "x")] == "unknown module"


# Bytes of a chain Ozone 12 itself saved (Rad Nu-disco master, 2026-10-23).
SAVED_CHAIN_B64 = ("ABAAAABNYXN0ZXIgUmViYWxhbmNlAAkAAABFcXVhbGl6ZXIABgAAAEltcGFjdAANAAAAU3Rl"
                   "cmVvIEltYWdlcgAHAAAAQ2xhcml0eQAKAAAAU3RhYmlsaXplcgAKAAAARHluYW1pYyBFUQAJ"
                   "AAAATWF4aW1pemVy")


def test_chain_bytes_roundtrip_ozone_saved_layout():
    import base64
    raw = base64.b64decode(SAVED_CHAIN_B64)
    names = osu.parse_chain_bytes(raw)
    assert names[0] == "Master Rebalance" and names[-1] == "Maximizer"
    assert osu.encode_chain_bytes(names) == raw


def test_ensure_in_chain_fills_an_empty_chain_maximizer_last():
    tree = _tree()
    assert osu.element_chain(tree) == []          # a freshly loaded Ozone
    added = osu.ensure_in_chain(tree, ["Maximizer", "Equalizer", "Stereo Imager"])
    assert added == ["Maximizer", "Equalizer", "Stereo Imager"]
    assert osu.element_chain(tree) == ["Equalizer", "Stereo Imager", "Maximizer"]
    assert osu.ensure_in_chain(tree, ["Equalizer"]) == []    # already there


def test_ensure_in_chain_refuses_non_chain_modules():
    with pytest.raises(ValueError):
        osu.ensure_in_chain(_tree(), ["Gain Input"])
