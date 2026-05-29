"""Pure helpers for generating Simpler .adv presets that load a chosen sample.

The audio file a Simpler plays is NOT exposed in Live's automatable parameter
API (only adsr/filter/lfo/etc. are), so it can only be set by writing a preset.
The factory-default Simpler has an EMPTY <SampleParts /> — there's no value to
patch — so we inject a full <MultiSamplePart> (key/velocity ranges, root key,
loop points, and the SampleRef file reference).

Proven against Live 11: OriginalCrc may be 0 (Live recomputes + relinks on
load), so the caller need not compute Ableton's CRC. The caller supplies the
sample's absolute path, byte size, frame count, and sample rate (frames/rate
read from the audio header server-side); this module is pure string assembly.
"""
from ableton_mcp_max.preset_patch import validate_preset_name, set_attr

_EMPTY_SAMPLEPARTS = "<SampleParts />"


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_multisample_part(sample_path, file_size, frames, sample_rate,
                           display_name, root_key=60,
                           relative_path=None, relative_path_type=0,
                           live_pack_name="", live_pack_id=""):
    """Assemble a single <MultiSamplePart> XML string for `sample_path`.

    frames/sample_rate may be 0 when unknown (Live recomputes on load), but a
    non-zero frames is strongly preferred so SampleEnd/loops are correct.
    """
    end = int(frames) if frames and int(frames) > 0 else 0
    rel = relative_path if relative_path is not None else _xml_escape(sample_path)
    fields = {
        "name": _xml_escape(display_name),
        "root": int(root_key),
        "end": end,
        "rel": rel,
        "abs": _xml_escape(sample_path),
        "rpt": int(relative_path_type),
        "size": int(file_size),
        "dur": end,
        "rate": int(sample_rate) if sample_rate else 44100,
        "pack": _xml_escape(live_pack_name),
        "packid": _xml_escape(live_pack_id),
    }
    return (
        '<MultiSamplePart Id="0" HasImportedSlicePoints="false" NeedsAnalysisData="false">'
        '<LomId Value="0" />'
        '<Name Value="%(name)s" />'
        '<Selection Value="true" /><IsActive Value="true" /><Solo Value="false" />'
        '<KeyRange><Min Value="0" /><Max Value="127" /><CrossfadeMin Value="0" /><CrossfadeMax Value="127" /></KeyRange>'
        '<VelocityRange><Min Value="1" /><Max Value="127" /><CrossfadeMin Value="1" /><CrossfadeMax Value="127" /></VelocityRange>'
        '<SelectorRange><Min Value="0" /><Max Value="127" /><CrossfadeMin Value="0" /><CrossfadeMax Value="127" /></SelectorRange>'
        '<RootKey Value="%(root)d" />'
        '<Detune Value="0" /><TuneScale Value="100" /><Panorama Value="0" /><Volume Value="1" /><Link Value="false" />'
        '<SampleStart Value="0" /><SampleEnd Value="%(end)d" />'
        '<SustainLoop><Start Value="0" /><End Value="%(end)d" /><Mode Value="0" /><Crossfade Value="0" /><Detune Value="0" /></SustainLoop>'
        '<ReleaseLoop><Start Value="0" /><End Value="%(end)d" /><Mode Value="3" /><Crossfade Value="0" /><Detune Value="0" /></ReleaseLoop>'
        '<SampleRef>'
        '<FileRef>'
        '<RelativePathType Value="%(rpt)d" />'
        '<RelativePath Value="%(rel)s" />'
        '<Path Value="%(abs)s" />'
        '<Type Value="2" />'
        '<LivePackName Value="%(pack)s" />'
        '<LivePackId Value="%(packid)s" />'
        '<OriginalFileSize Value="%(size)d" />'
        '<OriginalCrc Value="0" />'
        '</FileRef>'
        '<LastModDate Value="0" />'
        '<SourceContext />'
        '<SampleUsageHint Value="0" />'
        '<DefaultDuration Value="%(dur)d" />'
        '<DefaultSampleRate Value="%(rate)d" />'
        '</SampleRef>'
        '</MultiSamplePart>'
    ) % fields


def build_simpler_adv(default_xml, sample_path, file_size, frames, sample_rate,
                      name, root_key=60, relative_path=None,
                      relative_path_type=0, live_pack_name="",
                      live_pack_id=""):
    """Inject a sample into the empty factory Simpler default.

    Raises ValueError if `default_xml` lacks the empty <SampleParts /> slot
    (i.e. it's not a fresh Simpler default) or inputs are invalid.
    """
    disp = validate_preset_name(name)
    if not str(sample_path).strip():
        raise ValueError("sample_path is required.")
    if int(file_size) <= 0:
        raise ValueError("file_size must be a positive integer (bytes).")
    if _EMPTY_SAMPLEPARTS not in default_xml:
        raise ValueError(
            "default preset has no empty <SampleParts /> to inject into; "
            "pass a fresh factory Simpler default."
        )
    part = build_multisample_part(
        sample_path, file_size, frames, sample_rate, display_name=disp,
        root_key=root_key, relative_path=relative_path,
        relative_path_type=relative_path_type, live_pack_name=live_pack_name,
        live_pack_id=live_pack_id,
    )
    xml = default_xml.replace(
        _EMPTY_SAMPLEPARTS, "<SampleParts>" + part + "</SampleParts>", 1)
    xml = set_attr(xml, "UserName", disp, required=False)
    return xml
