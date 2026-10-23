"""Pure helpers for reading and writing Live's binary Preferences.cfg. No Live deps.

Live exposes no API for its preferences, so a preference the tools must control
(Auto-Warp Long Samples) is written straight into the file while Live is closed
(Live rewrites the file on quit, so a write while it runs is lost).

Layout (read off Live 12.4.6/12.4.7 on Windows):
- The file first declares each class: <u8 len><ascii class name><u32 field
  count>, then per field <u32 n><n UTF-16 chars><u8 type ref>; a ref of 0 is
  followed by the type inline (<u8 len><ascii type>), a non-zero ref points
  back to a type declared earlier.
- Later the same class name reappears as the value record: <u8 len><ascii
  name><u32 id>, then one value per field in declaration order. Bools are one
  byte, ints and enums four, a string is <u32 n><n UTF-16 chars>. FileRef values
  are not uniform, so a value is located by its fixed-size neighbours rather
  than by walking the record from its start.

Writes are refused unless the layout matches in exactly one place.
"""
import struct

FIXED_SIZES = {"RemoteableBool": 1, "RemoteableInt": 4, "RemoteableEnum": 4,
               "RemoteableFloat": 4}

# Preferences > Record/Warp/Launch > Auto-Warp Long Samples
AUTO_WARP_LONG_SAMPLES = ("SongPrefData", "LongClipAutoAutoWarp")

_MAX_STRING = 1024
_MAX_ENUM = 1024
_SCAN_WINDOW = 16384


def _header(cls):
    raw = cls.encode("ascii")
    return bytes([len(raw)]) + raw


def _u32(data, pos):
    if pos < 0 or pos + 4 > len(data):
        raise ValueError("truncated preferences data at %d" % pos)
    return struct.unpack_from("<I", data, pos)[0]


def class_fields(data, cls):
    """[(field_name, type_name)] declared for `cls`, in order. Type refs that
    point back to an earlier type come back as 'ref<N>'. Raises ValueError if
    the class is missing or its declaration does not parse."""
    i = data.find(_header(cls))
    if i < 0:
        raise ValueError("class %r not found in Preferences.cfg" % cls)
    p = i + len(_header(cls))
    count = _u32(data, p)
    p += 4
    if not 1 <= count <= 1000:
        raise ValueError("implausible field count %d for %r" % (count, cls))
    fields = []
    for _ in range(count):
        n = _u32(data, p)
        if not 1 <= n <= 200:
            raise ValueError("bad field name length %d in %r" % (n, cls))
        try:
            name = data[p + 4:p + 4 + 2 * n].decode("utf-16-le")
        except UnicodeDecodeError:
            raise ValueError("undecodable field name in %r" % cls)
        p += 4 + 2 * n
        if p >= len(data):
            raise ValueError("truncated declaration of %r" % cls)
        ref = data[p]
        p += 1
        if ref == 0:
            ln = data[p]
            typ = data[p + 1:p + 1 + ln].decode("latin-1")
            p += 1 + ln
        else:
            typ = "ref%d" % ref
        fields.append((name, typ))
    return fields


def _value_record_start(data, cls):
    """Offset of the first value after `cls`'s value-record header."""
    h = _header(cls)
    hits, i = [], data.find(h)
    while i >= 0:
        hits.append(i)
        i = data.find(h, i + 1)
    if len(hits) != 2:
        raise ValueError("expected %r twice (declaration + values), found %d"
                         % (cls, len(hits)))
    return hits[1] + len(h) + 4


def _fixed_ok(data, pos, types):
    """True if the fixed-size fields `types` laid out from `pos` look like
    values: every bool byte is 0 or 1 and every enum is a small index."""
    for t in types:
        if pos < 0 or pos + FIXED_SIZES[t] > len(data):
            return False
        if t == "RemoteableBool" and data[pos] not in (0, 1):
            return False
        if t == "RemoteableEnum" and struct.unpack_from("<I", data, pos)[0] >= _MAX_ENUM:
            return False
        pos += FIXED_SIZES[t]
    return True


def _string_ends_at(data, end):
    """True if some non-empty printable UTF-16 string value ends exactly at
    `end` (the previous variable-size field's last bytes)."""
    for n in range(1, _MAX_STRING + 1):
        pos = end - 4 - 2 * n
        if pos < 0:
            return False
        if struct.unpack_from("<I", data, pos)[0] == n and _string_end(data, pos) == end:
            return True
    return False


def _string_end(data, pos):
    """End offset of a printable UTF-16 string value at `pos`, or None."""
    if pos + 4 > len(data):
        return None
    n = struct.unpack_from("<I", data, pos)[0]
    end = pos + 4 + 2 * n
    if n > _MAX_STRING or end > len(data):
        return None
    for j in range(pos + 4, end, 2):
        if data[j + 1] == 0 and data[j] < 0x20:
            return None
    return end


def locate_bool(data, cls, key):
    """Byte offset of bool field `key`'s value in `cls`'s value record.

    Anchors on the nearest string field before `key`: that string must parse,
    the fixed-size fields between it and the previous variable-size field must
    end exactly where it starts, and the fixed fields after it up to `key` must
    follow it. Raises ValueError unless exactly one offset fits."""
    fields = class_fields(data, cls)
    names = [f for f, _ in fields]
    if key not in names:
        raise ValueError("%r has no field %r" % (cls, key))
    k = names.index(key)
    types = [t for _, t in fields]
    if types[k] != "RemoteableBool":
        raise ValueError("%r is %s, not a bool" % (key, types[k]))
    variable = [i for i in range(k) if types[i] not in FIXED_SIZES]
    if not variable or types[variable[-1]] != "RemoteableString":
        raise ValueError("no string field to anchor %r on" % key)
    v = variable[-1]
    u = variable[-2] if len(variable) > 1 else -1
    before = types[u + 1:v]
    after = types[v + 1:k + 1]
    before_len = sum(FIXED_SIZES[t] for t in before)
    after_len = sum(FIXED_SIZES[t] for t in after[:-1])

    start = _value_record_start(data, cls)
    hits = []
    for s in range(start + before_len, min(len(data), start + _SCAN_WINDOW)):
        end = _string_end(data, s)
        if end is None:
            continue
        if not _fixed_ok(data, s - before_len, before):
            continue
        if not _fixed_ok(data, end, after):
            continue
        if u >= 0 and not _string_ends_at(data, s - before_len):
            continue
        hits.append(end + after_len)
    if len(hits) != 1:
        raise ValueError("could not pin %r down (%d candidate offsets); this "
                         "Live version's Preferences.cfg layout is not "
                         "recognized" % (key, len(hits)))
    return hits[0]


def get_bool(data, cls, key):
    return bool(data[locate_bool(data, cls, key)])


def set_bool(data, cls, key, value):
    """Copy of `data` with bool `key` set to `value`."""
    pos = locate_bool(data, cls, key)
    out = bytearray(data)
    out[pos] = 1 if value else 0
    return bytes(out)
