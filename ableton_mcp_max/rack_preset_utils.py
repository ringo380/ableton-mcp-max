"""Pure helpers for patching Ableton rack presets (.adg). No Live dependencies.

The LOM exposes a rack's macro *values* and chain *names* but not macro
display-names/colors/defaults, chain key/velocity/chain-selector zones, or
macro->parameter mappings. Those live only in the gzipped rack XML. These
helpers (server-side only, like the other *_utils modules) read and patch that
XML by tag.

The one structural subtlety: a chain that hosts a sampler contains many nested
<MultiSamplePart> KeyRange/VelocityRange blocks, and drum racks contain many
<DrumBranchPreset> pads. So a chain-level zone is found as the zone block that
is a DIRECT CHILD of a top-level branch element (depth-aware), never "the first
KeyRange in the branch".
"""
import re

from ableton_mcp_max.preset_patch import validate_preset_name, validate_int_range

# rack kind -> tags + User Library destination + whether chains have key/vel zones.
RACK_TYPES = {
    "instrument": {
        "device_tag": "InstrumentGroupDevice",
        "branch_tag": "InstrumentBranchPreset",
        "category": "Instruments", "device_folder": "Instrument Rack",
        "has_key_velocity": True,
    },
    "audio_effect": {
        "device_tag": "AudioEffectGroupDevice",
        "branch_tag": "AudioEffectBranchPreset",
        "category": "Audio Effects", "device_folder": "Audio Effect Rack",
        "has_key_velocity": False,
    },
    "midi_effect": {
        "device_tag": "MidiEffectGroupDevice",
        "branch_tag": "MidiEffectBranchPreset",
        "category": "MIDI Effects", "device_folder": "MIDI Effect Rack",
        "has_key_velocity": False,
    },
    "drum": {
        "device_tag": "DrumGroupDevice",
        "branch_tag": "DrumBranchPreset",
        "category": "Drums", "device_folder": "Drum Rack",
        "has_key_velocity": True,
    },
}


def detect_rack_type(xml):
    """Return 'instrument'|'audio_effect'|'midi_effect'|'drum' for a rack .adg XML.

    Raises ValueError if no known rack device-type tag is present.
    """
    for kind, meta in RACK_TYPES.items():
        if "<%s" % meta["device_tag"] in xml:
            return kind
    raise ValueError(
        "not a recognized rack preset: no Instrument/AudioEffect/MidiEffect/"
        "Drum GroupDevice tag found."
    )


def _xml_unescape(s):
    return (str(s).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


# Container tags that establish nesting depth inside a branch. A zone or attr is
# a "direct child" of the branch when no container is open between the branch's
# own opening tag and the zone/attr.
_CONTAINERS = (
    "InstrumentBranchPreset", "AudioEffectBranchPreset", "MidiEffectBranchPreset",
    "DrumBranchPreset", "DeviceChain", "MultiSamplePart",
)
_ZONE_FIELDS = ("Min", "Max", "CrossfadeMin", "CrossfadeMax")


def top_branches(xml, branch_tag):
    """Return [(start, end), ...] spans of each TOP-LEVEL branch element.

    Depth-counts opens/closes of `branch_tag` so a rack-in-rack's inner branches
    are contained within (not counted as) a top-level span.
    """
    spans = []
    depth = 0
    start = None
    for m in re.finditer(r'<(/?)%s[ >]' % re.escape(branch_tag), xml):
        if m.group(1) == "":
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, m.end()))
                start = None
    return spans


def _branch_span(xml, branch_tag, chain_index):
    spans = top_branches(xml, branch_tag)
    if chain_index < 0 or chain_index >= len(spans):
        raise ValueError(
            "chain index %d out of range (rack has %d chains)."
            % (chain_index, len(spans))
        )
    return spans[chain_index]


def _direct_child_match(branch_xml, branch_tag, pattern):
    """Find the first regex match for `pattern` that is a DIRECT child of the
    branch (depth 0, skipping the branch's own opening tag). Returns the match
    object (offsets relative to branch_xml) or None.
    """
    container_re = re.compile(r'<(/?)(%s)[ >]' % "|".join(map(re.escape, _CONTAINERS)))
    target_re = re.compile(pattern, re.DOTALL)
    depth = 0
    saw_self = False
    pos = 0
    while pos < len(branch_xml):
        cm = container_re.search(branch_xml, pos)
        tm = target_re.search(branch_xml, pos)
        # The target counts only if it occurs before the next container token
        # AND we are currently at depth 0.
        if tm and (not cm or tm.start() < cm.start()):
            if depth == 0 and saw_self:
                return tm
            pos = tm.end()
            continue
        if not cm:
            return None
        tag = cm.group(2)
        closing = cm.group(1) == "/"
        if not saw_self and tag == branch_tag and not closing:
            saw_self = True  # the branch's own opening tag — don't count it
        elif closing:
            depth -= 1
        else:
            depth += 1
        pos = cm.end()
    return None


def read_chain_zone(xml, branch_tag, chain_index, zone_tag):
    """Return {min,max,crossfade_min,crossfade_max} for the chain-level zone, or
    None if that chain has no such zone (e.g. KeyRange on an audio-effect chain).
    """
    s, e = _branch_span(xml, branch_tag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, branch_tag, r'<%s>.*?</%s>' % (zone_tag, zone_tag))
    if not m:
        return None
    block = m.group(0)
    vals = dict(re.findall(r'<(Min|Max|CrossfadeMin|CrossfadeMax) Value="([^"]*)"', block))
    return {
        "min": int(vals["Min"]), "max": int(vals["Max"]),
        "crossfade_min": int(vals["CrossfadeMin"]),
        "crossfade_max": int(vals["CrossfadeMax"]),
    }


def chain_name(xml, branch_tag, chain_index):
    """Return the chain's display name (direct-child <UserName>), or ''."""
    s, e = _branch_span(xml, branch_tag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, branch_tag, r'<UserName Value="([^"]*)" />')
    return _xml_unescape(m.group(1)) if m else ""


from ableton_mcp_max.preset_patch import get_attr as _get_attr


def _macro_field(xml, prefix, index):
    """Value of <prefix.N Value="..."/> or None."""
    m = re.search(r'<%s\.%d Value="([^"]*)" />' % (re.escape(prefix), index), xml)
    return m.group(1) if m else None


def summarize_rack_adg(xml):
    """Structured summary of a rack .adg: type, visible-macro count, 16 macros,
    and per-chain zones. key_zone/velocity_zone are None on audio/midi-fx racks.
    """
    kind = detect_rack_type(xml)
    meta = RACK_TYPES[kind]
    btag = meta["branch_tag"]
    nvis = _get_attr(xml, "NumVisibleMacroControls")

    macros = []
    for i in range(16):
        name = _macro_field(xml, "MacroDisplayNames", i)
        color = _macro_field(xml, "MacroColor", i)
        default = _macro_field(xml, "MacroDefaults", i)
        macros.append({
            "macro": i + 1,
            "name": _xml_unescape(name) if name is not None else "",
            "color": int(color) if color is not None and color.lstrip("-").isdigit() else None,
            "default": float(default) if default is not None else None,
        })

    chains = []
    for ci in range(len(top_branches(xml, btag))):
        entry = {
            "chain": ci,
            "name": chain_name(xml, btag, ci),
            "chain_selector_zone": read_chain_zone(xml, btag, ci, "BranchSelectorRange"),
        }
        if meta["has_key_velocity"]:
            entry["key_zone"] = read_chain_zone(xml, btag, ci, "KeyRange")
            entry["velocity_zone"] = read_chain_zone(xml, btag, ci, "VelocityRange")
        else:
            entry["key_zone"] = None
            entry["velocity_zone"] = None
        chains.append(entry)

    return {
        "rack_type": kind,
        "num_visible_macros": int(nvis) if nvis is not None and nvis.isdigit() else None,
        "macros": macros,
        "chains": chains,
    }
