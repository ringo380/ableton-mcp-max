from ableton_mcp_max import als_automation_utils as au

XML = (
    '<Ableton><LiveSet><Tracks>'
    '<AudioTrack><X>1</X></AudioTrack>'
    '<ReturnTrack><R>A</R></ReturnTrack>'
    '<ReturnTrack><R>B</R></ReturnTrack>'
    '</Tracks>'
    '<MasterTrack><M>master here</M></MasterTrack>'
    '</LiveSet></Ableton>'
)


def test_find_master_track_span():
    s, e = au.find_master_track_span(XML)
    assert "master here" in XML[s:e]
    assert XML[s:].startswith("<MasterTrack>")


def test_find_return_track_span():
    s, e = au.find_return_track_span(XML, 1)
    assert "<R>B</R>" in XML[s:e]
