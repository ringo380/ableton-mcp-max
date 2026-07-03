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


XML_LIVE12 = (
    '<Ableton><LiveSet><Tracks>'
    '<AudioTrack><X>1</X></AudioTrack>'
    '</Tracks>'
    '<MainTrack SelectedToolPanel="7" SelectedGeneratorName=""><M>main here</M></MainTrack>'
    '</LiveSet></Ableton>'
)


def test_find_master_track_span():
    s, e = au.find_master_track_span(XML)
    assert "master here" in XML[s:e]
    assert XML[s:].startswith("<MasterTrack>")


def test_find_master_track_span_live12_maintrack():
    # Live 12 renamed <MasterTrack> to <MainTrack>; the helper must accept it.
    s, e = au.find_master_track_span(XML_LIVE12)
    assert "main here" in XML_LIVE12[s:e]
    assert XML_LIVE12[s:].startswith("<MainTrack ")
    assert XML_LIVE12[s:e].endswith("</MainTrack>")


def test_find_return_track_span():
    s, e = au.find_return_track_span(XML, 1)
    assert "<R>B</R>" in XML[s:e]
