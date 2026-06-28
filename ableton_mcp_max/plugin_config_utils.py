"""Encode/parse Live's plugin Configure-list XML (the VST/AU param exposure backdoor).

The LOM exposes only a third-party plugin's *Configured* parameters as
DeviceParameters (a fresh Serum 2 shows just `Device On`), and there is no LOM
API to Configure. But Live persists the Configure list as a pool of
`<PluginFloatParameter>` slots inside the plugin device's `<ParameterList>` in
the saved `.als`. Filling an empty slot with a real `ParameterId`/`ParameterName`
/`Manual`/`VisualIndex` makes that parameter a live, settable DeviceParameter
after the set reloads.

An EMPTY slot carries sentinels: ParameterId=-1, Manual=0.1234567687,
VisualIndex=1073741823 (0x3FFFFFFF). A FILLED slot also needs unique
`AutomationTarget`/`ModulationTarget` Ids; those must stay below the document's
global `<NextPointeeId>`, which must be advanced past every id we allocate (else
Live rejects the set: "NextPointeeId is too low"). Allocate ids FROM
`<NextPointeeId>` via `bump_next_pointee_id`, then pass that start id to
`fill_slots`.

All functions are pure (XML string in, XML string out). No Live deps.
"""
import binascii
import json
import re
import struct

EMPTY_PARAM_ID = -1
EMPTY_MANUAL = "0.1234567687"
EMPTY_VISUAL = "1073741823"

_SLOT_RE = re.compile(r'<PluginFloatParameter Id="(\d+)">.*?</PluginFloatParameter>', re.S)
_EMPTY_MARK = '<ParameterId Value="-1" />'


def _xml_escape(s):
    """Escape &, <, > for an XML attribute value (matches rack_preset_utils)."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def count_slots(parameter_list_xml):
    """Number of <PluginFloatParameter> slots (empty or filled)."""
    return len(_SLOT_RE.findall(parameter_list_xml))


def find_empty_slots(parameter_list_xml):
    """Slot Ids (the Id="N" attribute) of unconfigured slots, in document order."""
    out = []
    for m in _SLOT_RE.finditer(parameter_list_xml):
        if _EMPTY_MARK in m.group(0):
            out.append(int(m.group(1)))
    return out


def max_target_id(full_xml):
    """Largest Automation/ModulationTarget Id in the doc (0 if none)."""
    ids = [int(x) for x in re.findall(r'<(?:Automation|Modulation)Target Id="(\d+)"', full_xml)]
    return max(ids) if ids else 0


def build_slot(slot_id, param_id, name, manual, visual_index, auto_id, mod_id):
    """Render one filled <PluginFloatParameter> block.

    `manual` is the parameter's value in NATIVE units (the LOM reads/sets it
    normalized 0-1, but the stored Manual is native, e.g. 1547.45 Hz). `name` is
    XML-escaped. `auto_id`/`mod_id` must be unique in the document and below
    <NextPointeeId>.
    """
    return (
        '<PluginFloatParameter Id="%d">\n'
        '\t\t\t\t\t\t<ParameterName Value="%s" />\n'
        '\t\t\t\t\t\t<ParameterId Value="%d" />\n'
        '\t\t\t\t\t\t<ParameterIdFlankBool Value="false" />\n'
        '\t\t\t\t\t\t<VisualIndex Value="%d" />\n'
        '\t\t\t\t\t\t<ParameterValue>\n'
        '\t\t\t\t\t\t\t<LomId Value="0" />\n'
        '\t\t\t\t\t\t\t<Manual Value="%s" />\n'
        '\t\t\t\t\t\t\t<MidiControllerRange>\n'
        '\t\t\t\t\t\t\t\t<Min Value="0" />\n'
        '\t\t\t\t\t\t\t\t<Max Value="1" />\n'
        '\t\t\t\t\t\t\t</MidiControllerRange>\n'
        '\t\t\t\t\t\t\t<AutomationTarget Id="%d">\n'
        '\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />\n'
        '\t\t\t\t\t\t\t</AutomationTarget>\n'
        '\t\t\t\t\t\t\t<ModulationTarget Id="%d">\n'
        '\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />\n'
        '\t\t\t\t\t\t\t</ModulationTarget>\n'
        '\t\t\t\t\t\t</ParameterValue>\n'
        '\t\t\t\t\t\t<LastUserRange>\n'
        '\t\t\t\t\t\t\t<First Value="Invalid" />\n'
        '\t\t\t\t\t\t\t<Last Value="Invalid" />\n'
        '\t\t\t\t\t\t</LastUserRange>\n'
        '\t\t\t\t\t\t<LastInternalRange>\n'
        '\t\t\t\t\t\t\t<First Value="0" />\n'
        '\t\t\t\t\t\t\t<Last Value="1" />\n'
        '\t\t\t\t\t\t</LastInternalRange>\n'
        '\t\t\t\t\t</PluginFloatParameter>'
    ) % (slot_id, _xml_escape(name), param_id, visual_index, manual, auto_id, mod_id)


def fill_slots(parameter_list_xml, params, start_target_id):
    """Replace the first N empty slots with the given params.

    `params`: list of dicts {param_id, name, manual, visual_index}. Each filled
    slot consumes two sequential target ids from `start_target_id`. Returns
    (new_xml, dropped_count) where dropped_count is the params that did not fit
    (caller should log() the overflow). Empty slots are filled in document order,
    keeping each slot's existing Id attribute.
    """
    empty_ids = find_empty_slots(parameter_list_xml)
    n = min(len(params), len(empty_ids))
    dropped = len(params) - n
    # build {slot_id -> rendered block} for the slots we fill
    replacements = {}
    tid = start_target_id
    for i in range(n):
        slot_id = empty_ids[i]
        p = params[i]
        replacements[slot_id] = build_slot(
            slot_id, p["param_id"], p["name"], p["manual"], p["visual_index"], tid, tid + 1
        )
        tid += 2

    def _sub(m):
        sid = int(m.group(1))
        return replacements.get(sid, m.group(0))

    new_xml = _SLOT_RE.sub(_sub, parameter_list_xml)
    return new_xml, dropped


PLUGIN_DEVICE_TAGS = ("PluginDevice", "AuPluginDevice")

_TAG_RE = re.compile(r'<(/?)([A-Za-z0-9_]+)((?:\s[^>]*?)?)(/?)>')


def _matching_close(xml, tag, open_end):
    """Index just past the `</tag>` that closes an element whose open tag ends at
    `open_end`. Counts nested same-named opens; ignores self-closing tags."""
    depth = 1
    for m in _TAG_RE.finditer(xml, open_end):
        closing, name, _, selfclose = m.groups()
        if selfclose or name != tag:
            continue
        if closing:
            depth -= 1
            if depth == 0:
                return m.end()
        else:
            depth += 1
    raise ValueError("unterminated <%s>" % tag)


def _top_level_children(xml, inner_start, inner_end):
    """(tag, open_start, open_end, self_closing) for each direct child element in
    xml[inner_start:inner_end] (depth-0 within that range, document order)."""
    out = []
    depth = 0
    for m in _TAG_RE.finditer(xml, inner_start):
        if m.start() >= inner_end:
            break
        closing, name, _, selfclose = m.groups()
        if selfclose:
            if depth == 0:
                out.append((name, m.start(), m.end(), True))
            continue
        if closing:
            depth -= 1
        else:
            if depth == 0:
                out.append((name, m.start(), m.end(), False))
            depth += 1
    return out


def locate_param_list(full_xml, track_start, track_end, device_index,
                      plugin_tags=PLUGIN_DEVICE_TAGS):
    """Char span (start, end) of the `<ParameterList>...</ParameterList>` of the
    `device_index`-th device in the track's main device chain.

    `track_start`/`track_end` bound one track's XML (e.g. from
    `als_automation_utils.find_track_span`). Navigates: the track's main
    `<Devices>` container -> its depth-0 child elements (the devices) -> the
    device_index-th child -> that device's `<ParameterList>`. Does NOT match the
    first `<ParameterList>` blindly (mixer sends etc. have their own).

    Raises ValueError if the device isn't a plugin (tag not in `plugin_tags`),
    the index is out of range, or no ParameterList is found.
    """
    dev_open = full_xml.find("<Devices>", track_start, track_end)
    if dev_open == -1:
        raise ValueError("track has no <Devices> chain")
    dev_inner = dev_open + len("<Devices>")
    dev_close = _matching_close(full_xml, "Devices", dev_inner)
    children = _top_level_children(full_xml, dev_inner, dev_close)
    if device_index >= len(children):
        raise ValueError("device index %d out of range (%d devices)"
                         % (device_index, len(children)))
    tag, c_start, c_open_end, selfclose = children[device_index]
    if tag not in plugin_tags:
        raise ValueError("device %d is a <%s>, not a VST/AU plugin "
                         "(expected one of %s)" % (device_index, tag, plugin_tags))
    dev_end = _matching_close(full_xml, tag, c_open_end)
    pl_open = full_xml.find("<ParameterList>", c_open_end, dev_end)
    if pl_open == -1:
        raise ValueError("plugin device %d has no <ParameterList>" % device_index)
    pl_end = _matching_close(full_xml, "ParameterList", pl_open + len("<ParameterList>"))
    return pl_open, pl_end


def bump_next_pointee_id(full_xml, count):
    """Advance the global <NextPointeeId> by 2*count and return (xml, start_id).

    `start_id` is the first id to allocate (the pre-bump counter value); the two
    ids per slot (count slots -> 2*count ids) all stay below the new counter, as
    Live requires. Raises ValueError if no <NextPointeeId> is present.
    """
    m = re.search(r'<NextPointeeId Value="(\d+)"\s*/>', full_xml)
    if not m:
        raise ValueError("no <NextPointeeId> in document")
    start = int(m.group(1))
    new = start + 2 * count
    out = full_xml[:m.start()] + '<NextPointeeId Value="%d" />' % new + full_xml[m.end():]
    return out, start


def _state_inner_span(full_xml, search_from, search_to, tag):
    """Return (inner_start, inner_end) of the hex text inside <tag>...</tag>,
    searching within [search_from, search_to). Returns None if not found."""
    m = re.compile(r"<%s[^>]*>" % tag).search(full_xml, search_from, search_to)
    if not m:
        return None
    close = full_xml.find("</%s>" % tag, m.end(), search_to)
    if close < 0:
        return None
    return (m.end(), close)


def locate_plugin_state(full_xml, track_start, track_end, device_index):
    """Return inner-hex spans of the device_index-th plugin device's
    <ProcessorState> and <ControllerState> within [track_start, track_end).

    A VST3/AU plugin device holds exactly one of each. Returns a dict with
    keys 'processor' and 'controller', each a (start, end) char-index pair
    bracketing the raw hex text (exclusive of the XML tags themselves).

    Raises ValueError if the device_index-th ProcessorState or its paired
    ControllerState are not found within the track span.
    """
    proc_iter = list(re.finditer(r"<ProcessorState[^>]*>",
                                 full_xml[track_start:track_end]))
    if device_index >= len(proc_iter):
        raise ValueError("no plugin ProcessorState #%d in track" % device_index)
    base = track_start
    proc_start = base + proc_iter[device_index].start()
    proc = _state_inner_span(full_xml, proc_start, track_end, "ProcessorState")
    if proc is None:
        raise ValueError("ProcessorState close tag not found for device %d"
                         % device_index)
    ctrl = _state_inner_span(full_xml, proc[1], track_end, "ControllerState")
    if ctrl is None:
        raise ValueError("ControllerState not found for device %d" % device_index)
    return {"processor": proc, "controller": ctrl}


def is_serum_state(inner_hex):
    """Return True if inner_hex is the hex-encoded XferJson blob for a Serum2 plugin.

    Decodes the container header (magic 'XferJson', 8-byte length, JSON metadata)
    and checks that the 'product' field equals 'Serum2'.
    """
    h = "".join(inner_hex.split())
    try:
        blob = binascii.unhexlify(h[: len(h) // 2 * 2])
        if blob[:8] != b"XferJson":
            return False
        jlen = struct.unpack("<Q", blob[9:17])[0]
        meta = json.loads(blob[17:17 + jlen].decode("utf-8"))
        return meta.get("product") == "Serum2"
    except Exception:
        return False
