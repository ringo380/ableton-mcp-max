"""Codec for Ozone 12's plugin-state container (found inside an .als
<ProcessorState> blob). Server-side only - the Remote Script cannot import this.

Framing (verified): 4-byte magic DE8A6800 + uint32-LE version + uint32-LE field3
(= 4 + len(zlib payload)) + uint32-LE raw_len (= decompressed byte length) +
zlib stream. The zlib stream decompresses to UTF-8 JSON in iZotope's
typed-dictionary format: every value is {"Type": <T>, "Value": <v>}.
"""
import binascii
import json
import struct
import zlib

MAGIC = b"\xDE\x8A\x68\x00"


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


def decode(blob):
    if blob[:4] != MAGIC:
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


_SETTABLE = ("Float", "Bool", "UInt")


def _module_dict(tree, module):
    elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    if module not in elems:
        raise ValueError("unknown module")
    return elems[module]["Value"]


def module_leaves(tree, module):
    md = _module_dict(tree, module)
    out = {}
    for name, node in md.items():
        if isinstance(node, dict) and "Type" in node and "Value" in node:
            out[name] = {"type": node["Type"], "value": node["Value"]}
    return out


def get_param(tree, module, param):
    md = _module_dict(tree, module)
    node = md.get(param)
    if not (isinstance(node, dict) and "Type" in node and "Value" in node):
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
    if not (isinstance(node, dict) and "Type" in node and "Value" in node):
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
