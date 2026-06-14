from ableton_mcp_max.tap_registry import parse_frames

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
