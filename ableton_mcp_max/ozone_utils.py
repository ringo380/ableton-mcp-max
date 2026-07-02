"""Pure module model for iZotope Ozone 12 (host-side only).

Ozone 12 exposes 873 host params named `MODULE: [Stereo/Main|Aux] <role> [band]`.
This module parses those names into a structured model, holds the module
registry, packs a chosen module set into Ableton's 128 Configure slots, and maps
values between LOM-normalized 0-1 and native units. Imported by server.py only.
"""
import re

MODULES = {
    "EQ": "Equalizer",
    "EQ2": "Equalizer 2",
    "IMG": "Imager",
    "MAX": "Maximizer",
    "DYN": "Dynamics",
    "DYNEQ": "Dynamic EQ",
    "EXC": "Exciter",
    "VCOMP": "Vintage Compressor",
    "VEQ": "Vintage EQ",
    "VLIM": "Vintage Limiter",
    "VTAPE": "Vintage Tape",
    "SPSHPR": "Spectral Shaper",
    "MREBAL": "Master Rebalance",
    "MATCH EQ": "Match EQ",
    "LEF": "Low End Focus",
    "IMP": "Impact",
    "STBL": "Stabilizer",
    "CLA": "Clarity",
    "BAS": "Bass Control",
    "STEMEQ": "Stem EQ",
    "UNLIMITER": "Unlimiter",
    "GAIN": "Gain",
}

# module keys sorted longest-first so "MATCH EQ" wins over a bare "EQ" prefix
_MODULE_KEYS = sorted(MODULES, key=len, reverse=True)
_TRAIL_BAND = re.compile(r"\s+(\d+)$")


def parse_param_name(name):
    """Parse one Ozone host param name into a structured record.

    Returns {module, module_name, section, role, band, raw}. A name with no
    `MODULE:` prefix (e.g. 'Global Bypass') yields module/module_name/section
    None and role = the whole lowercased name.
    """
    raw = name
    module = None
    rest = name
    if ":" in name:
        head, tail = name.split(":", 1)
        if head in MODULES:
            module = head
            rest = tail.strip()
    if module is None:
        return {"module": None, "module_name": None, "section": None,
                "role": name.strip().lower(), "band": None, "raw": raw}
    section = None
    if rest.startswith("Stereo/Main"):
        section = "stereo_main"
        rest = rest[len("Stereo/Main"):].strip()
    elif rest.startswith("Aux"):
        section = "aux"
        rest = rest[len("Aux"):].strip()
    band = None
    # Extract band number (can be anywhere in the string, not just trailing)
    parts = rest.split()
    for i, part in enumerate(parts):
        if part.isdigit():
            band = int(part)
            parts.pop(i)
            break
    rest = ' '.join(parts)
    return {"module": module, "module_name": MODULES[module], "section": section,
            "role": rest.lower(), "band": band, "raw": raw}
