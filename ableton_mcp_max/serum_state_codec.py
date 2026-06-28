"""Codec for Serum 2's XferJson plugin-state container (as found in .SerumPreset
files and inside an .als <ProcessorState>/<ControllerState> blob).

Framing (verified): b"XferJson" + b"\\x00" + uint64-LE meta-json-len + meta-json
+ 8-byte header (<II = uint32 uncompressed-cbor-len, uint32 flags=2) + zstd-frame.
meta["hash"] = md5(zstd_blob).hexdigest() (32 hex chars).
"""
import binascii
import hashlib
import json
import struct

import cbor2
import zstandard as zstd

_MAGIC = b"XferJson"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class DecodedState(object):
    __slots__ = ("meta", "meta_bytes", "tree")

    def __init__(self, meta, meta_bytes, tree):
        self.meta = meta
        self.meta_bytes = meta_bytes
        self.tree = tree


def from_hex(hexstr):
    h = "".join(hexstr.split())
    return binascii.unhexlify(h[: len(h) // 2 * 2])


def to_hex(blob):
    return binascii.hexlify(blob).decode("ascii").upper()


def decode(blob):
    if blob[:8] != _MAGIC:
        raise ValueError("not an XferJson container")
    jlen = struct.unpack("<Q", blob[9:17])[0]
    meta_bytes = blob[17:17 + jlen]
    meta = json.loads(meta_bytes.decode("utf-8"))
    z = blob.find(_ZSTD_MAGIC, 17 + jlen)
    if z < 0:
        raise ValueError("no zstd blob found")
    cbor = zstd.ZstdDecompressor().decompress(blob[z:], max_output_size=64 * 1024 * 1024)
    tree = cbor2.loads(cbor)
    return DecodedState(meta, meta_bytes, tree)


def encode(state, tree):
    cbor = cbor2.dumps(tree)
    zblob = zstd.ZstdCompressor().compress(cbor)
    new_hash = hashlib.md5(zblob).hexdigest()
    old_hash = state.meta["hash"]
    if len(new_hash) != len(old_hash):
        raise ValueError("hash length mismatch")
    meta_bytes = state.meta_bytes.replace(old_hash.encode("ascii"),
                                          new_hash.encode("ascii"), 1)
    header = struct.pack("<II", len(cbor), 2)
    return (_MAGIC + b"\x00" + struct.pack("<Q", len(meta_bytes))
            + meta_bytes + header + zblob)
