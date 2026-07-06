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
