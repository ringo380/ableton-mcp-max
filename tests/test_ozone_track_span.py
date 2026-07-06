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


# Real Live 11/12 sets emit return/main tracks WITH attributes, and a sibling
# <ReturnTracksListWrapper> that shares the <ReturnTrack> prefix. The span
# finders must match the attribute-bearing tags without matching the wrapper.
XML_REAL_ATTRS = (
    '<Ableton><LiveSet><Tracks>'
    '<AudioTrack Id="1"><X>1</X></AudioTrack>'
    '<ReturnTrack Id="2" SelectedToolPanel="7"><R>A here</R></ReturnTrack>'
    '<ReturnTrack Id="3" SelectedToolPanel="7"><R>B here</R></ReturnTrack>'
    '</Tracks>'
    '<ReturnTracksListWrapper LomId="0" />'
    '<MainTrack Id="9" SelectedToolPanel="7"><M>main here</M></MainTrack>'
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


def test_find_return_track_span_real_attrs():
    # Real Live sets emit <ReturnTrack Id="2" ...>; the literal-match version
    # never fired. Also must not match sibling <ReturnTracksListWrapper .../>.
    s0, e0 = au.find_return_track_span(XML_REAL_ATTRS, 0)
    assert "A here" in XML_REAL_ATTRS[s0:e0]
    assert XML_REAL_ATTRS[s0:].startswith("<ReturnTrack ")
    assert XML_REAL_ATTRS[s0:e0].endswith("</ReturnTrack>")
    s1, e1 = au.find_return_track_span(XML_REAL_ATTRS, 1)
    assert "B here" in XML_REAL_ATTRS[s1:e1]
    assert "A here" not in XML_REAL_ATTRS[s1:e1]


def test_find_master_track_span_real_attrs_maintrack():
    s, e = au.find_master_track_span(XML_REAL_ATTRS)
    assert "main here" in XML_REAL_ATTRS[s:e]
    assert XML_REAL_ATTRS[s:].startswith("<MainTrack ")
