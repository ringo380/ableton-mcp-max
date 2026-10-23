import os
import sys

from ableton_mcp_max import platform_utils as plat
import glob, pytest
from ableton_mcp_max import groove_preset_utils as gpu

SYNTH_AGR = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Ableton MajorVersion="5" MinorVersion="11.0_423">\n'
    '  <Groove>\n'
    '    <LomId Value="0" />\n'
    '    <Name Value="Test &amp; Feel" />\n'
    '    <Clip>\n'
    '      <Value>\n'
    '        <MidiClip Id="0" Time="0">\n'
    '          <ScaleInformation>\n'
    '            <RootNote Value="0" />\n'
    '            <Name Value="Major" />\n'
    '          </ScaleInformation>\n'
    '          <IsInKey Value="false" />\n'
    '          <Notes><KeyTracks /></Notes>\n'
    '        </MidiClip>\n'
    '      </Value>\n'
    '    </Clip>\n'
    '  </Groove>\n'
    '</Ableton>\n'
)

def test_groove_pool_name_unescapes():
    assert gpu.groove_pool_name(SYNTH_AGR) == "Test & Feel"

def test_agr_to_pool_groove_sets_id_and_keeps_name():
    out = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=3)
    assert out.startswith('<Groove Id="3">')
    assert out.rstrip().endswith('</Groove>')
    assert '<Name Value="Test &amp; Feel" />' in out

def test_agr_to_pool_groove_drops_groove_lomid():
    # The Groove-level LomId is removed; the MidiClip body is preserved.
    out = gpu.agr_to_pool_groove(SYNTH_AGR)
    # No <LomId> as a direct child right after <Groove Id="0">
    head = out.split("<Clip>")[0]
    assert "<LomId" not in head

def test_agr_to_pool_groove_strips_cosmetic_nodes():
    out = gpu.agr_to_pool_groove(SYNTH_AGR)
    for tag in ("ScaleInformation", "IsInKey"):
        assert tag not in out
    assert "<Notes>" in out  # groove-defining data preserved

def test_agr_to_pool_groove_strips_original_file_ref():
    # ~8 factory grooves carry a Live-11 <OriginalFileRef> whose
    # <RelativePathElement Dir=.. Id=..> a Live-12 LiveSet rejects. It is
    # provenance only and must be stripped; the groove <Notes> must survive.
    agr = SYNTH_AGR.replace(
        "<Notes><KeyTracks /></Notes>",
        "<Notes><KeyTracks /></Notes>\n"
        "          <OriginalFileRef>\n"
        "            <FileRef Id=\"0\">\n"
        "              <RelativePath>\n"
        "                <RelativePathElement Dir=\"Grooves\" Id=\"0\" />\n"
        "              </RelativePath>\n"
        "            </FileRef>\n"
        "          </OriginalFileRef>")
    out = gpu.agr_to_pool_groove(agr)
    assert "OriginalFileRef" not in out
    assert "RelativePathElement" not in out
    assert "<Notes>" in out  # groove data preserved


def _factory_agr():
    hits = glob.glob(os.path.join(plat.core_library_glob(sys.platform), "Grooves", "**", "*.agr"),
                     recursive=True)
    # Find the first text file (skip binary .agr files).
    for path in hits:
        try:
            with open(path, encoding='utf-8') as f:
                f.read(100)
            return path
        except (UnicodeDecodeError, IOError):
            continue
    return None

_FACTORY_AGR = _factory_agr()

@pytest.mark.skipif(_FACTORY_AGR is None, reason="no factory .agr installed")
def test_real_factory_agr_round_trip():
    agr_path = _FACTORY_AGR
    with open(agr_path, encoding='utf-8') as f:
        xml = f.read()
    name = gpu.groove_pool_name(xml)
    assert name and "<" not in name
    entry = gpu.agr_to_pool_groove(xml, groove_id=0)
    assert entry.startswith('<Groove Id="0">')
    for tag in ("ScaleInformation", "IsInKey"):
        assert tag not in entry
    assert "<Notes>" in entry  # real grooves carry note timing


WRAPPER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Ableton MajorVersion="5" MinorVersion="12.0_12402">\n'
    '  <LiveSet>\n'
    '    <Tracks><MidiTrack><DeviceChain><DeviceChain><Devices>'
    '<InstrumentGroupDevice><X/></InstrumentGroupDevice>'
    '</Devices></DeviceChain></DeviceChain></MidiTrack></Tracks>\n'
    '    <MidiClip Time="0">\n'
    '      <GrooveSettings>\n'
    '        <GrooveId Value="-1" />\n'
    '      </GrooveSettings>\n'
    '    </MidiClip>\n'
    '    <GroovePool>\n'
    '      <LomId Value="0" />\n'
    '      <Grooves />\n'
    '      <DefaultGrooveId Value="-1" />\n'
    '      <GroovesListWrapper LomId="0" />\n'
    '    </GroovePool>\n'
    '  </LiveSet>\n'
    '</Ableton>\n'
)

def test_build_carrier_injects_groove_and_refs():
    entry = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=0)
    out = gpu.build_carrier_alc(WRAPPER, entry, groove_id=0)
    assert "<Grooves>" in out and "<Grooves />" not in out
    assert '<Groove Id="0">' in out
    assert '<DefaultGrooveId Value="0" />' in out
    assert '<GrooveId Value="0" />' in out
    assert '<GrooveId Value="-1" />' not in out

def test_build_carrier_preserves_nested_device_chain():
    # The wrapper's (possibly nested) device chain must be left intact - emptying
    # nested <Devices> with a flat regex corrupts the XML (live load failed with
    # "mismatched tag"). Assert the nested device block survives VERBATIM, so the
    # tag nesting stays balanced. The carrier loads onto a throwaway scratch track
    # that is deleted right after, so the instrument never reaches a user track.
    entry = gpu.agr_to_pool_groove(SYNTH_AGR, groove_id=0)
    out = gpu.build_carrier_alc(WRAPPER, entry, groove_id=0)
    assert "<Devices />" not in out
    nested = ('<Devices><InstrumentGroupDevice><X/></InstrumentGroupDevice>'
              '</Devices></DeviceChain></DeviceChain>')
    assert nested in out                        # device nesting preserved verbatim
    assert out.count("<Devices>") == out.count("</Devices>")  # balanced


def _mk_groove_tree(tmp_path):
    d = tmp_path / "Grooves" / "Style"
    d.mkdir(parents=True)
    for n in ("Rock Fatback 16ths", "Disco Live Feel 16ths", "Swing 8ths"):
        (d / (n + ".agr")).write_text("<Ableton><Groove/></Ableton>")
    return [(str(tmp_path / "Grooves"), "factory")]

def test_list_grooves_query_or_match(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    rows = gpu.list_grooves(roots, query="disco swing")
    names = {r["name"] for r in rows}
    assert names == {"Disco Live Feel 16ths", "Swing 8ths"}
    assert all(r["category"] == "Style" and r["source"] == "factory" for r in rows)

def test_list_grooves_empty_query_all_and_limit(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    assert len(gpu.list_grooves(roots, query="")) == 3
    assert len(gpu.list_grooves(roots, query="", limit=2)) == 2

def test_resolve_single_match(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    p = gpu.resolve_groove_source("rock fatback 16ths", roots)
    assert p.endswith("Rock Fatback 16ths.agr")

def test_resolve_existing_path_passthrough(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    direct = roots[0][0] + "/Style/Swing 8ths.agr"
    assert gpu.resolve_groove_source(direct, roots) == direct

def test_resolve_no_match_raises(tmp_path):
    roots = _mk_groove_tree(tmp_path)
    with pytest.raises(ValueError):
        gpu.resolve_groove_source("nonexistent groove", roots)

def test_is_xml_agr_and_read_guard(tmp_path):
    xmlf = tmp_path / "x.agr"
    xmlf.write_text("<?xml version='1.0'?>\n<Ableton><Groove/></Ableton>")
    binf = tmp_path / "b.agr"
    binf.write_bytes(b"\xab\x1eVx\x03\x93\x00\x00Groove!")
    assert gpu.is_xml_agr(str(xmlf)) is True
    assert gpu.is_xml_agr(str(binf)) is False
    assert gpu.read_groove_xml(str(xmlf)).startswith("<?xml")
    with pytest.raises(ValueError):
        gpu.read_groove_xml(str(binf))

def test_list_grooves_flags_loadable(tmp_path):
    d = tmp_path / "Grooves" / "S"; d.mkdir(parents=True)
    (d / "TextGroove.agr").write_text("<Ableton><Groove/></Ableton>")
    (d / "BinGroove.agr").write_bytes(b"\xab\x1eVx\x00\x00")
    rows = gpu.list_grooves([(str(tmp_path / "Grooves"), "factory")])
    by = {r["name"]: r["loadable"] for r in rows}
    assert by == {"TextGroove": True, "BinGroove": False}

def test_resolve_multi_match_raises(tmp_path):
    d = tmp_path / "Grooves" / "A"; d.mkdir(parents=True)
    d2 = tmp_path / "Grooves" / "B"; d2.mkdir(parents=True)
    (d / "Swing.agr").write_text("x"); (d2 / "Swing.agr").write_text("x")
    roots = [(str(tmp_path / "Grooves"), "factory")]
    with pytest.raises(ValueError):
        gpu.resolve_groove_source("swing", roots)


def test_pool_has_name():
    pool = [{"index": 0, "name": "Swing 16ths 66"}]
    assert gpu.pool_has_name(pool, "Swing 16ths 66") == 0
    assert gpu.pool_has_name(pool, "Rock Fatback") is None
