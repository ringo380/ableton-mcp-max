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
import math
import re

from ableton_mcp_max.preset_patch import validate_preset_name, validate_int_range, get_attr as _get_attr

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

    Detects by the rack device-type tag that appears EARLIEST in the document:
    that is the top-level rack's own device. (A drum rack's pads embed
    InstrumentGroupDevice, and an instrument rack may embed a nested drum rack,
    so a presence-only check would misread the outer type — position decides.)
    Raises ValueError if no known rack device-type tag is present.
    """
    best_kind, best_pos = None, None
    for kind, meta in RACK_TYPES.items():
        pos = xml.find("<%s" % meta["device_tag"])
        if pos != -1 and (best_pos is None or pos < best_pos):
            best_pos, best_kind = pos, kind
    if best_kind is None:
        raise ValueError(
            "not a recognized rack preset: no Instrument/AudioEffect/MidiEffect/"
            "Drum GroupDevice tag found."
        )
    return best_kind


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
                # m.end() lands on the closing tag's '>' because the [ >] char
                # class consumes it (XML closing tags carry no attributes).
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


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _set_macro_field(xml, prefix, index, value):
    """Replace Value on <prefix.N Value="..."/>; raise if that macro slot absent."""
    pattern = r'(<%s\.%d Value=")[^"]*("\s*/>)' % (re.escape(prefix), index)
    new, n = re.subn(pattern, lambda m: m.group(1) + str(value) + m.group(2), xml)
    if n == 0:
        raise ValueError("macro slot <%s.%d> not found in preset." % (prefix, index))
    return new


def _check_macro_number(num):
    if isinstance(num, bool) or not isinstance(num, int):
        raise ValueError("macro number must be an int 1..16, got %r." % (num,))
    if not (1 <= num <= 16):
        raise ValueError("macro number %d out of range 1..16." % num)
    return num - 1  # -> 0-based XML index


def patch_macros(xml, names=None, colors=None, defaults=None):
    """Patch macro display names / colors / defaults in a rack .adg XML.

    names/colors/defaults are dicts keyed by 1-based macro number. Only listed
    macros change. Names are XML-escaped; a literal double-quote is rejected.
    Colors are ints >= 0; defaults are floats 0..127. Pure: returns new XML.
    """
    out = xml
    for num, name in (names or {}).items():
        idx = _check_macro_number(num)
        text = str(name)
        if '"' in text:
            raise ValueError("macro %d name must not contain a double-quote." % num)
        out = _set_macro_field(out, "MacroDisplayNames", idx, _xml_escape(text))
    for num, color in (colors or {}).items():
        idx = _check_macro_number(num)
        c = validate_int_range(color, -1, 69, "macro %d color" % num)
        out = _set_macro_field(out, "MacroColor", idx, c)
    for num, dflt in (defaults or {}).items():
        idx = _check_macro_number(num)
        try:
            f = float(dflt)
        except (TypeError, ValueError):
            raise ValueError("macro %d default must be a number 0..127." % num)
        if not (0.0 <= f <= 127.0):
            raise ValueError("macro %d default %s out of range 0..127." % (num, f))
        out = _set_macro_field(out, "MacroDefaults", idx, "%.6g" % f)
    return out


# tool zone key -> XML zone tag.
_ZONE_TAGS = {
    "key": "KeyRange",
    "velocity": "VelocityRange",
    "chain_selector": "BranchSelectorRange",
}


def normalize_zone(value, label):
    """Coerce a zone arg into {min,max,crossfade_min,crossfade_max} and validate.

    Accepts shorthand [min, max] (crossfades = min/max, i.e. no crossfade) or a
    full object. Enforces 0..127 ints and min <= crossfade_min <= crossfade_max
    <= max.
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError("%s shorthand must be [min, max]." % label)
        lo = validate_int_range(value[0], 0, 127, "%s min" % label)
        hi = validate_int_range(value[1], 0, 127, "%s max" % label)
        z = {"min": lo, "max": hi, "crossfade_min": lo, "crossfade_max": hi}
    elif isinstance(value, dict):
        lo = validate_int_range(value.get("min"), 0, 127, "%s min" % label)
        hi = validate_int_range(value.get("max"), 0, 127, "%s max" % label)
        cmin = validate_int_range(value.get("crossfade_min", lo), 0, 127, "%s crossfade_min" % label)
        cmax = validate_int_range(value.get("crossfade_max", hi), 0, 127, "%s crossfade_max" % label)
        z = {"min": lo, "max": hi, "crossfade_min": cmin, "crossfade_max": cmax}
    else:
        raise ValueError("%s must be [min, max] or an object." % label)
    if z["min"] > z["max"]:
        raise ValueError("%s min %d must be <= max %d." % (label, z["min"], z["max"]))
    if not (z["min"] <= z["crossfade_min"] <= z["crossfade_max"] <= z["max"]):
        raise ValueError(
            "%s requires min <= crossfade_min <= crossfade_max <= max "
            "(got %s)." % (label, z)
        )
    return z


# Matches one XML tag token: opening <Tag ...>, self-closing <Tag ... />, or close </Tag>.
# Attribute values may contain '/', so selfclose is the trailing '/' immediately before '>'.
_TAG_TOKEN = re.compile(r'<(/?)([A-Za-z0-9_.]+)((?:\s[^>]*?)?)(/?)>')


def _child_elements(element_xml):
    """Return [(tag, start, end), ...] for the DIRECT child elements of the single
    element whose full text is `element_xml` (it starts with the element's own
    opening tag and ends with its closing tag). Offsets are relative to
    element_xml. Handles self-closing children and arbitrary nesting/tag names.

    Assumes well-formed Ableton XML with no unencoded '>' inside attribute values
    (Live encodes these as '&gt;'; same assumption as `_direct_child_match`).
    """
    spans = []
    depth = 0
    stack = []
    seen_root = False
    for m in _TAG_TOKEN.finditer(element_xml):
        closing, tag, _attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if not seen_root:
            # first token is the root element's own opening tag
            seen_root = True
            depth = 1
            continue
        if closing:
            depth -= 1
            if depth == 1:
                st_tag, st_pos = stack.pop()
                spans.append((st_tag, st_pos, m.end()))
            elif depth == 0:
                break  # root element closed
        elif selfclose == "/":
            if depth == 1:
                spans.append((tag, m.start(), m.end()))
        else:
            if depth == 1:
                stack.append((tag, m.start()))
            depth += 1
    return spans


def _find_child(element_xml, tag):
    """Return (start, end) of the first direct-child element named `tag`, or None."""
    for t, s, e in _child_elements(element_xml):
        if t == tag:
            return (s, e)
    return None


_KEYMIDI_TEMPLATE = (
    "<KeyMidi>"
    '<PersistentKeyString Value="" />'
    '<IsNote Value="false" />'
    '<Channel Value="16" />'
    '<NoteOrController Value="%d" />'
    '<LowerRangeNote Value="-1" />'
    '<UpperRangeNote Value="-1" />'
    '<ControllerMapMode Value="0" />'
    "</KeyMidi>"
)


# Device wrappers inside a chain's <DevicePresets>. A plain device is an
# <AbletonDevicePreset>; a NESTED rack is a <GroupDevicePreset> (it carries the
# rack's chains in a <BranchPresets> sibling of its <Device>). Both count toward
# the device index, in document (chain) order — matching get_rack_chains.
_DEVICE_WRAPPERS = ("AbletonDevicePreset", "GroupDevicePreset")


def _locate_device_in_region(region, branch_tag, chain_index, device_index, step_i):
    """Find the device at (chain_index, device_index) WITHIN `region`.

    Navigates branch -> DevicePresets -> Nth device wrapper -> Device -> device
    element. Returns (device_tag, dev_start, dev_end, wrap_start, wrap_end) RELATIVE
    to `region`: the device-element span (for param lookup / rack-type detection)
    and the enclosing wrapper span (whose <BranchPresets> holds a nested rack's
    chains). Errors carry the path step index `step_i` so multi-level failures are
    debuggable.
    """
    spans = top_branches(region, branch_tag)
    if chain_index < 0 or chain_index >= len(spans):
        raise ValueError(
            "chain index %d out of range at path step %d (level has %d chain(s))."
            % (chain_index, step_i, len(spans)))
    bs, be = spans[chain_index]
    branch = region[bs:be]

    dp = _find_child(branch, "DevicePresets")
    if not dp:
        raise ValueError(
            "chain %d at path step %d has no <DevicePresets> (no devices)."
            % (chain_index, step_i))
    dp_base = bs + dp[0]
    devicepresets = branch[dp[0]:dp[1]]

    devs = [(s, e) for (t, s, e) in _child_elements(devicepresets)
            if t in _DEVICE_WRAPPERS]
    if device_index < 0 or device_index >= len(devs):
        raise ValueError(
            "device index %d out of range at path step %d (chain %d has %d device(s))."
            % (device_index, step_i, chain_index, len(devs)))
    ds, de = devs[device_index]
    wrap_base = dp_base + ds
    wrap = devicepresets[ds:de]

    dev = _find_child(wrap, "Device")
    if not dev:
        raise ValueError(
            "device %d at path step %d has no <Device> wrapper." % (device_index, step_i))
    dev_base = wrap_base + dev[0]
    device_block = wrap[dev[0]:dev[1]]

    devkids = _child_elements(device_block)
    if not devkids:
        raise ValueError(
            "device %d at path step %d <Device> has no device element."
            % (device_index, step_i))
    dtag, des, dee = devkids[0]
    return dtag, dev_base + des, dev_base + dee, wrap_base, dp_base + de


def _descend_to_device(xml, outer_branch_tag, steps):
    """Walk `steps` (list of {chain, device}) descending one rack level per step.

    Returns (device_tag, absolute_start, absolute_end) of the FINAL step's device
    element. Every non-final step's device must itself be a nested rack (a
    <GroupDevicePreset>); its branch_tag is detected from its own GroupDevice tag
    (which may differ from the outer rack's, e.g. an Audio Effect Rack nested in an
    Instrument Rack), and the descent continues into the wrapper's <BranchPresets>
    (a sibling of <Device>, NOT inside the device element).
    """
    region = xml
    region_base = 0
    branch_tag = outer_branch_tag
    last = len(steps) - 1
    for i, step in enumerate(steps):
        dtag, ds, de, ws, we = _locate_device_in_region(
            region, branch_tag, step["chain"], step["device"], i)
        abs_dev_start, abs_dev_end = region_base + ds, region_base + de
        if i == last:
            return dtag, abs_dev_start, abs_dev_end
        device_el = xml[abs_dev_start:abs_dev_end]
        try:
            nested_kind = detect_rack_type(device_el)
        except ValueError:
            raise ValueError(
                "path step %d targets device <%s>, which is not a rack; cannot "
                "descend to step %d." % (i, dtag, i + 1))
        branch_tag = RACK_TYPES[nested_kind]["branch_tag"]
        # The nested rack's chains live in the wrapper's <BranchPresets> sibling.
        wrap = xml[region_base + ws:region_base + we]
        bp = _find_child(wrap, "BranchPresets")
        if not bp:
            raise ValueError(
                "path step %d nested rack <%s> has no <BranchPresets>." % (i, dtag))
        abs_bp_start = region_base + ws + bp[0]
        region = xml[abs_bp_start:region_base + ws + bp[1]]
        region_base = abs_bp_start
    raise ValueError("path must have at least one step.")  # pragma: no cover


def _locate_param_in_device(xml, dtag, base_el, end_el, parameter, where):
    """Return absolute (start, end) of `parameter` as a direct child of the device
    element spanning [base_el, end_el). Raises with the device's available tags.
    """
    device_el = xml[base_el:end_el]
    p = _find_child(device_el, parameter)
    if not p:
        avail = sorted({t for (t, s, e) in _child_elements(device_el)})
        raise ValueError(
            "parameter <%s> not found as a direct child of device <%s> (%s). "
            "Available: %s" % (parameter, dtag, where, ", ".join(avail)))
    return base_el + p[0], base_el + p[1]


def _locate_param_by_path(xml, outer_branch_tag, steps, parameter):
    """Return absolute (start, end) of the target parameter, descending `steps`
    (list of {chain, device}) into nested racks as needed.
    """
    dtag, bs, be = _descend_to_device(xml, outer_branch_tag, steps)
    where = "path " + "/".join("c%dd%d" % (s["chain"], s["device"]) for s in steps)
    return _locate_param_in_device(xml, dtag, bs, be, parameter, where)


def _locate_param(xml, branch_tag, chain_index, device_index, parameter):
    """Single-level shim over `_locate_param_by_path` (backward-compatible).

    Navigates branch -> DevicePresets -> Nth AbletonDevicePreset -> Device ->
    device element -> direct-child <parameter>. The parameter is matched by the
    FIRST direct-child element with that tag name (unique for real device params).
    """
    return _locate_param_by_path(
        xml, branch_tag, [{"chain": chain_index, "device": device_index}], parameter)


def _inject_keymidi(param_el, macro_index):
    """Return param_el with a <KeyMidi> mapping for `macro_index` (0-based).

    Idempotent: if a <KeyMidi> already exists, replace its NoteOrController;
    otherwise insert after the param's first <LomId .../> (or after the opening
    tag if it has none).
    """
    if "<KeyMidi>" in param_el:
        return re.sub(
            r'(<KeyMidi>.*?<NoteOrController Value=")[^"]*(".*?</KeyMidi>)',
            lambda m: m.group(1) + str(macro_index) + m.group(2),
            param_el, count=1, flags=re.S)
    block = _KEYMIDI_TEMPLATE % macro_index
    lom = re.search(r'<LomId Value="[^"]*" />', param_el)
    if lom:
        return param_el[:lom.end()] + block + param_el[lom.end():]
    ot = re.match(r'<[A-Za-z0-9_.]+(?:\s[^>]*?)?>', param_el)
    if not ot:
        raise ValueError("malformed parameter element; cannot inject mapping.")
    return param_el[:ot.end()] + block + param_el[ot.end():]


def _set_controller_range(param_el, lo, hi):
    """Set the macro-mapping range by replacing <Min>/<Max> inside the param's
    <MidiControllerRange>. Values are in the parameter's NATIVE stored units (the
    same units as the param's <Manual> / the LOM DeviceParameter.min..max), NOT
    0..127. Inversion is expressed by lo > hi (written verbatim, never sorted).

    Every automatable param carries a <MidiControllerRange> (it holds the param's
    full native range by default), so this replaces in place — no synthesis.
    Raises if the param somehow has none.
    """
    m = re.search(r'<MidiControllerRange>.*?</MidiControllerRange>', param_el, re.S)
    if not m:
        raise ValueError("parameter has no <MidiControllerRange> to set a range on.")
    block = m.group(0)
    block = re.sub(
        r'(<Min Value=")[^"]*("\s*/>)',
        lambda mm: mm.group(1) + ("%.10g" % lo) + mm.group(2), block, count=1)
    block = re.sub(
        r'(<Max Value=")[^"]*("\s*/>)',
        lambda mm: mm.group(1) + ("%.10g" % hi) + mm.group(2), block, count=1)
    return param_el[:m.start()] + block + param_el[m.end():]


def _normalize_range(value):
    """Coerce a mapping 'range' into (lo, hi) floats in the param's native units.

    Requires an object {min, max}; both finite numbers. Inversion is allowed
    (lo > hi) and preserved. No 0..127 clamp — native units are param-specific
    (e.g. linear amplitude, Hz, dB).
    """
    if not isinstance(value, dict):
        raise ValueError(
            "mapping 'range' must be an object {min, max} in native param units.")
    if value.get("min") is None or value.get("max") is None:
        raise ValueError("mapping 'range' requires both 'min' and 'max'.")
    try:
        lo = float(value["min"])
        hi = float(value["max"])
    except (TypeError, ValueError):
        raise ValueError("mapping 'range' min/max must be numbers.")
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("mapping 'range' min/max must be finite numbers.")
    return lo, hi


def _normalize_path(mp):
    """Resolve a mapping's device address into a list of {chain, device} steps.

    Accepts either the flat single-level form ({chain, device}) or an explicit
    `path` array of {chain, device} steps for nested rack-in-rack addressing.
    Supplying both is rejected as ambiguous.
    """
    has_path = mp.get("path") is not None
    has_flat = mp.get("chain") is not None or mp.get("device") is not None
    if has_path and has_flat:
        raise ValueError(
            "mapping must use EITHER 'path' OR 'chain'/'device', not both.")
    if has_path:
        path = mp["path"]
        if not isinstance(path, (list, tuple)) or not path:
            raise ValueError("'path' must be a non-empty list of {chain, device} steps.")
        steps = []
        for i, step in enumerate(path):
            if not isinstance(step, dict):
                raise ValueError("path step %d must be a {chain, device} object." % i)
            for key in ("chain", "device"):
                if step.get(key) is None:
                    raise ValueError(
                        "path step %d requires '%s' (an integer index)." % (i, key))
            steps.append({"chain": int(step["chain"]), "device": int(step["device"])})
        return steps
    for key in ("chain", "device"):
        if mp.get(key) is None:
            raise ValueError(
                "mapping requires '%s' (an integer index), or a 'path' array." % key)
    return [{"chain": int(mp["chain"]), "device": int(mp["device"])}]


def patch_macro_mappings(xml, rack_type, mappings):
    """Add macro->parameter mappings to a rack .adg XML. Pure: returns new XML.

    Each mapping is an object:
      {macro (1-based), parameter (XML tag name within the device), AND a device
       address — either flat {chain (0-based), device (0-based)} OR a nested
       `path` array of {chain, device} steps descending one rack level each.}

    A `path` lets a mapping target a parameter inside a nested rack-in-rack (the
    nested rack's branch type is auto-detected and may differ from the outer's).
    The flat form {chain, device} is equivalent to a one-step path.

    Optional `range` ({min, max}) sets a custom mapping range so the macro sweeps
    a sub-range of the parameter; min/max are in the param's NATIVE units and
    min > max inverts the mapping. Omitting `range` leaves the param's full-range
    mapping (its <MidiControllerRange> is untouched). Many params may share a
    macro. Re-mapping a param replaces its existing mapping.
    """
    btag = RACK_TYPES[rack_type]["branch_tag"]
    out = xml
    for mp in mappings:
        if not isinstance(mp, dict):
            raise ValueError("each mapping must be an object.")
        macro_index = _check_macro_number(mp.get("macro"))  # 0-based, validates 1..16
        steps = _normalize_path(mp)
        parameter = str(mp.get("parameter", "")).strip()
        if not parameter:
            raise ValueError("mapping requires a 'parameter' tag name.")
        rng = mp.get("range")
        lo_hi = _normalize_range(rng) if rng is not None else None
        ps, pe = _locate_param_by_path(out, btag, steps, parameter)
        seg = _inject_keymidi(out[ps:pe], macro_index)
        if lo_hi is not None:
            seg = _set_controller_range(seg, lo_hi[0], lo_hi[1])
        out = out[:ps] + seg + out[pe:]
    return out


def patch_chain_zone(xml, rack_type, chain_index, zone_key, value):
    """Patch chain `chain_index`'s `zone_key` ('key'|'velocity'|'chain_selector').

    `rack_type` is from detect_rack_type. Raises if key/velocity is requested on
    a rack type whose chains lack them (audio_effect/midi_effect). Pure.
    """
    if zone_key not in _ZONE_TAGS:
        raise ValueError("unknown zone %r (use key|velocity|chain_selector)." % zone_key)
    meta = RACK_TYPES[rack_type]
    if zone_key in ("key", "velocity") and not meta["has_key_velocity"]:
        raise ValueError(
            "%s racks have no %s zone (only chain_selector)." % (rack_type, zone_key)
        )
    z = normalize_zone(value, zone_key)
    zone_tag = _ZONE_TAGS[zone_key]
    btag = meta["branch_tag"]
    s, e = _branch_span(xml, btag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, btag, r'<%s>.*?</%s>' % (zone_tag, zone_tag))
    if not m:
        raise ValueError(
            "chain %d has no <%s> to patch." % (chain_index, zone_tag)
        )
    block = m.group(0)
    for field, key in (("Min", "min"), ("Max", "max"),
                       ("CrossfadeMin", "crossfade_min"), ("CrossfadeMax", "crossfade_max")):
        block = re.sub(
            r'(<%s Value=")[^"]*("\s*/>)' % field,
            lambda mm, v=z[key]: mm.group(1) + str(v) + mm.group(2),
            block, count=1,
        )
    new_branch = branch[:m.start()] + block + branch[m.end():]
    return xml[:s] + new_branch + xml[e:]
