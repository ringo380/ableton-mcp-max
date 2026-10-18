"""Codec for Ozone 12's plugin-state container (found inside an .als
<ProcessorState> blob). Server-side only - the Remote Script cannot import this.

Framing (verified): 4-byte magic DE8A6800 + uint32-LE version + uint32-LE field3
(= 4 + len(zlib payload)) + uint32-LE raw_len (= decompressed byte length) +
zlib stream. The zlib stream decompresses to UTF-8 JSON in iZotope's
typed-dictionary format: every value is {"Type": <T>, "Value": <v>}.
"""
import base64
import binascii
import json
import re
import struct
import zlib

MAGIC = b"\xDE\x8A\x68\x00"

# Other iZotope plugins use the same framing with their own magic (verified on
# Live 12.4.6 / Windows: Neutron 5 and Nectar 4 blobs decode with it). Writes
# stay Ozone-only (is_ozone_state guards set_ozone_state); these are for reads.
FAMILY_MAGICS = {
    MAGIC: "Ozone 12",
    b"\x83\xFB\x80\x00": "Neutron 5",
    b"\xFC\x84\x68\x00": "Nectar 4",
}


class DecodedState(object):
    __slots__ = ("version", "tree")

    def __init__(self, version, tree):
        self.version = version
        self.tree = tree


def from_hex(hexstr):
    h = "".join(hexstr.split())
    return binascii.unhexlify(h[: len(h) // 2 * 2])


def to_hex(blob):
    return binascii.hexlify(blob).decode("ascii").upper()


def decode(blob, magics=(MAGIC,)):
    if blob[:4] not in magics:
        raise ValueError("not an Ozone state blob")
    version = struct.unpack("<I", blob[4:8])[0]
    raw_len = struct.unpack("<I", blob[12:16])[0]
    raw = zlib.decompress(blob[16:], bufsize=64 * 1024 * 1024)
    if len(raw) != raw_len:
        raise ValueError("raw length mismatch: header %d, actual %d"
                         % (raw_len, len(raw)))
    return DecodedState(version, json.loads(raw.decode("utf-8")))


def encode(state, tree):
    raw = json.dumps(tree, separators=(",", ":")).encode("utf-8")
    z = zlib.compress(raw, 9)
    header = (MAGIC + struct.pack("<I", state.version)
              + struct.pack("<I", 4 + len(z)) + struct.pack("<I", len(raw)))
    return header + z


def is_ozone_state(inner_hex):
    try:
        return from_hex(inner_hex)[:4] == MAGIC
    except Exception:
        return False


def family_product(inner_hex):
    """Product name ('Ozone 12', 'Neutron 5', 'Nectar 4') of an iZotope state
    blob, from its magic; None for anything else."""
    try:
        return FAMILY_MAGICS.get(from_hex(inner_hex[:16])[:4])
    except Exception:
        return None


def _elements(tree):
    return tree["DSP State"]["Value"]["DSP Elements"]["Value"]


def parse_chain_bytes(raw):
    """Decode an Element Chain 'Extra Bytes' payload into module names, in
    signal order. Neutron/Nectar store [u32-LE len][name] per slot; Ozone adds a
    one-byte prefix before each slot. A slot is read as [len][name] when the
    length is plausible and the name is printable, else one prefix byte is
    skipped. Returns [] for an empty or undecodable payload."""
    names, i, n = [], 0, len(raw)

    def _name_at(pos):
        if pos + 4 > n:
            return None
        ln = struct.unpack("<I", raw[pos:pos + 4])[0]
        if not 0 < ln <= 64 or pos + 4 + ln > n:
            return None
        s = raw[pos + 4:pos + 4 + ln]
        if not all(32 <= c < 127 for c in s):
            return None
        return s.decode("ascii")

    while i < n:
        name = _name_at(i)
        if name is not None:
            names.append(name)
            i += 4 + len(name)
            continue
        name = _name_at(i + 1)
        if name is None:
            break
        names.append(name)
        i += 5 + len(name)
    return names


def element_chain(tree):
    """Ordered module names in the plugin's active signal chain. Modules that
    exist in the state but are not in the chain do not process audio."""
    elems = _elements(tree)
    node = elems.get("ElementChain") or elems.get("Element Chain")
    if not node:
        return []
    extra = node.get("Value", {}).get("Extra Bytes", {}).get("Value")
    if not extra:
        return []
    try:
        return parse_chain_bytes(base64.b64decode(extra))
    except (ValueError, binascii.Error):
        return []


def _leaf_value(md, *names):
    for n in names:
        node = md.get(n)
        if _is_leaf(node):
            return node["Value"]
    return None


def _element_for(elems, name):
    """The DSP element a chain entry names. Chain entries use each element's
    'Element Name' field, which can differ from its key (Neutron stores
    'Hybrid Dynamic EQ' under the key 'Dynamic EQ')."""
    if name in elems:
        return elems[name]
    for node in elems.values():
        md = node.get("Value") if isinstance(node, dict) else None
        if isinstance(md, dict) and _leaf_value(md, "Element Name") == name:
            return node
    return None


def _round(v, nd=2):
    # Blob floats carry float32 noise (-0.10000038...); report dB to 0.01.
    return round(v, nd) if isinstance(v, float) else v


def _module_bypassed(elems, name):
    node = _element_for(elems, name)
    if not node:
        return None
    md = node.get("Value", {})
    v = _leaf_value(md, "Bypass", "BYPASS")
    return bool(v) if v is not None else None


def ozone_input_gain(elems):
    """Effective Ozone input trim in dB. With Input Lock on (Ozone's default)
    the plugin uses 'Gain Input Locked' and ignores Left/Right - measured by
    render 2026-10-17: Left/Right -6 changed nothing, Locked -6 cut 5-6 LU."""
    node = elems.get("Gain Input")
    md = node.get("Value") if isinstance(node, dict) else None
    if not isinstance(md, dict):
        return None
    if _leaf_value(md, "Input Lock"):
        return _round(_leaf_value(md, "Gain Input Locked"))
    left = _leaf_value(md, "Gain Input Left")
    right = _leaf_value(md, "Gain Input Right")
    if all(isinstance(v, (int, float)) and not isinstance(v, bool)
           for v in (left, right)):
        return _round((left + right) / 2.0)
    return _round(left if left is not None else right)


def summarize_family(tree, product):
    """Compact read of one iZotope instance: product, global bypass, the active
    chain with per-module bypass, and the limiting stage when one is in the
    chain (Ozone Maximizer: target loudness, Margin = output ceiling, Prevent
    Intersample Clipping = true-peak safe; Neutron/Nectar Limiter: ceiling)."""
    elems = _elements(tree)
    glob = elems.get("Global", {}).get("Value", {})
    gb = _leaf_value(glob, "Global Bypass", "GLOBAL_BYPASS")
    chain = element_chain(tree)
    out = {
        "product": product,
        "global_bypass": bool(gb) if gb is not None else False,
        "chain": [{"module": m, "bypass": _module_bypassed(elems, m)} for m in chain],
        "limiter": None,
    }
    active = [c["module"] for c in out["chain"] if not c["bypass"]]
    if "Maximizer" in active:
        md = _element_for(elems, "Maximizer")["Value"]
        out["limiter"] = {
            "module": "Maximizer",
            "target_lufs": _round(_leaf_value(md, "Target Loudness [dB]")),
            "ceiling_db": _round(_leaf_value(md, "Margin")),
            "true_peak_safe": bool(_leaf_value(md, "Prevent Intersample Clipping")),
            "mode": _leaf_value(md, "Mode"),
            "character": _leaf_value(md, "Character"),
            # Target Loudness is only the auto-learn goal; output level follows
            # the Maximizer Gain (drive, >= 0) and the Ozone input trim.
            "gain_db": _round(_leaf_value(md, "Gain")),
            "input_gain_db": ozone_input_gain(elems),
        }
    elif "Limiter" in active:
        md = _element_for(elems, "Limiter")["Value"]
        out["limiter"] = {
            "module": "Limiter",
            "target_lufs": None,
            "ceiling_db": _round(_leaf_value(md, "Ceiling", "THRESHOLD")),
            "true_peak_safe": None,
            "mode": _leaf_value(md, "Algorithm"),
            "character": _leaf_value(md, "Character"),
        }
    return out


_PROC_OPEN = re.compile(r"<ProcessorState[^>]*>")


def _iter_processor_states(xml, s, e):
    """Yield (ordinal, inner_hex) per <ProcessorState> open in [s, e), counted
    the way plugin_config_utils.locate_processor_state counts them (so the
    ordinal is a valid get_ozone_state device_index). Self-closing states yield
    an empty string."""
    for ordinal, m in enumerate(_PROC_OPEN.finditer(xml, s, e)):
        if m.group(0).endswith("/>"):
            yield ordinal, ""
            continue
        close = xml.find("</ProcessorState>", m.end(), e)
        yield ordinal, (xml[m.end():close] if close != -1 else "")


def scan_family_states(xml, spans):
    """Summarize every iZotope instance in the given track spans.

    spans: iterable of (track_type, index, start, end) (see
    als_automation_utils.iter_track_spans). Returns {(track_type, index):
    [summary, ...]} in document order; each summary also carries
    `plugin_ordinal` (the device's position among the track's ProcessorStates,
    i.e. the device_index get_ozone_state takes). Blobs that fail to decode are
    reported with an `error` instead of being dropped."""
    out = {}
    for ttype, idx, s, e in spans:
        found = []
        for ordinal, inner in _iter_processor_states(xml, s, e):
            product = family_product(inner.lstrip())
            if product is None:
                continue
            try:
                st = decode(from_hex(inner), magics=tuple(FAMILY_MAGICS))
                summ = summarize_family(st.tree, product)
            except Exception as ex:
                summ = {"product": product, "error": str(ex)}
            summ["plugin_ordinal"] = ordinal
            found.append(summ)
        if found:
            out[(ttype, idx)] = found
    return out


def _module_dict(tree, module):
    elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    if module not in elems:
        raise ValueError("unknown module")
    return elems[module]["Value"]


def _is_leaf(node):
    return isinstance(node, dict) and "Type" in node and "Value" in node


def module_leaves(tree, module):
    md = _module_dict(tree, module)
    out = {}
    for name, node in md.items():
        if _is_leaf(node):
            out[name] = {"type": node["Type"], "value": node["Value"]}
    return out


def get_param(tree, module, param):
    md = _module_dict(tree, module)
    node = md.get(param)
    if not _is_leaf(node):
        raise ValueError("unknown param")
    return {"type": node["Type"], "value": node["Value"]}


def _coerce(t, value):
    # bool is a subclass of int; guard it explicitly per target type.
    if t == "Bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError("type mismatch")
    if t == "Float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("type mismatch")
        return float(value)
    if t == "UInt":
        if isinstance(value, bool):
            raise ValueError("type mismatch")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int) or value < 0:
            raise ValueError("type mismatch")
        return value
    raise ValueError("unsupported type")


def set_param(tree, module, param, value):
    md = _module_dict(tree, module)          # raises "unknown module"
    node = md.get(param)
    if not _is_leaf(node):
        raise ValueError("unknown param")
    coerced = _coerce(node["Type"], value)   # raises "unsupported type"/"type mismatch"
    node["Value"] = coerced
    return coerced


def apply_changes(tree, changes):
    applied, skipped = [], []
    for module, params in changes.items():
        for param, value in params.items():
            try:
                coerced = set_param(tree, module, param, value)
                applied.append({"module": module, "param": param, "value": coerced})
            except ValueError as e:
                skipped.append({"module": module, "param": param, "reason": str(e)})
    return applied, skipped
