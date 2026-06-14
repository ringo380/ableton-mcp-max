from ableton_mcp_max.tap_registry import parse_frames, TapState

def test_parse_single_frame():
    frames, rest = parse_frames('{"type":"hello","track":{"uuid":"a"}}\n')
    assert len(frames) == 1
    assert frames[0]["type"] == "hello"
    assert rest == ""

def test_parse_partial_frame_buffers_remainder():
    frames, rest = parse_frames('{"type":"block"}\n{"type":"par')
    assert len(frames) == 1
    assert rest == '{"type":"par'

def test_parse_multiple_frames():
    frames, rest = parse_frames('{"a":1}\n{"b":2}\n')
    assert len(frames) == 2
    assert frames[0]["a"] == 1 and frames[1]["b"] == 2

def test_parse_ignores_blank_lines():
    frames, rest = parse_frames('\n{"a":1}\n\n')
    assert len(frames) == 1

def test_parse_skips_malformed_complete_line():
    frames, rest = parse_frames('not json\n{"a":1}\n')
    assert len(frames) == 1
    assert frames[0]["a"] == 1


def test_hello_registers_track():
    s = TapState(buffer_max=4)
    s.handle_frame("conn1", {"type":"hello","track":{"uuid":"u1","name":"Bass","index":2,"kind":"midi"},"sample_rate":48000})
    assert s.tracks()[0]["name"] == "Bass"
    assert s.tracks()[0]["uuid"] == "u1"

def test_block_appends_to_ring_and_evicts():
    s = TapState(buffer_max=2)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"}})
    for i in range(3):
        s.handle_frame("c", {"type":"block","data":{"rms":i}})
    buf = s.buffer("u1")
    assert len(buf) == 2
    assert [b["rms"] for b in buf] == [1, 2]   # oldest evicted

def test_reset_clears_buffer():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"}})
    s.handle_frame("c", {"type":"block","data":{"rms":9}})
    s.reset("u1")
    assert s.buffer("u1") == []

def test_reset_all_clears_every_buffer():
    s = TapState(buffer_max=4)
    s.handle_frame("a", {"type":"hello","track":{"uuid":"u1"}})
    s.handle_frame("b", {"type":"hello","track":{"uuid":"u2"}})
    s.handle_frame("a", {"type":"block","data":{"rms":1}})
    s.handle_frame("b", {"type":"block","data":{"rms":2}})
    s.reset()
    assert s.buffer("u1") == [] and s.buffer("u2") == []

def test_block_before_hello_is_dropped():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"block","data":{"rms":1}})
    assert s.tracks() == []

def test_hello_without_uuid_ignored():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"hello","track":{"name":"NoId"}})
    assert s.tracks() == []

def test_tracks_reports_sample_rate_and_block_count():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"},"sample_rate":44100})
    s.handle_frame("c", {"type":"block","data":{"rms":1}})
    t = s.tracks()[0]
    assert t["sample_rate"] == 44100 and t["block_count"] == 1

def test_drop_conn_keeps_buffer_but_unlinks_connection():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"}})
    s.handle_frame("c", {"type":"block","data":{"rms":1}})
    s.drop_conn("c")
    # buffer retained (last-known data), but new blocks on that conn id are dropped
    assert s.buffer("u1") == [{"rms":1}]
    s.handle_frame("c", {"type":"block","data":{"rms":2}})
    assert s.buffer("u1") == [{"rms":1}]
