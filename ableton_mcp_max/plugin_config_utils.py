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
import re

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
