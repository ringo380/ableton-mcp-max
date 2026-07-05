"""Pure module model for iZotope Ozone 12 (host-side only).

Ozone 12 exposes 873 host params named `MODULE: [Stereo/Main|Aux] <role> [band]`.
This module parses those names into a structured model, holds the module
registry, packs a chosen module set into Ableton's 128 Configure slots, and maps
values between LOM-normalized 0-1 and native units. Imported by server.py only.
"""

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


def pack_modules(params, modules, cap=128):
    """Select params belonging to `modules` (in module-list order), capped at
    `cap` Configure slots. Returns {selected, dropped, overflow}."""
    wanted = list(modules)
    by_mod = {}
    for p in params:
        by_mod.setdefault(p.get("module"), []).append(p)
    selected = []
    overflow = []
    for mod in wanted:
        mod_params = by_mod.get(mod, [])
        room = cap - len(selected)
        if room <= 0:
            if mod_params:
                overflow.append(mod)
            continue
        take = mod_params[:room]
        selected.extend(take)
        if len(take) < len(mod_params):
            overflow.append(mod)
    total_wanted = sum(len(by_mod.get(m, [])) for m in wanted)
    dropped = total_wanted - len(selected)
    return {"selected": selected, "dropped": dropped, "overflow": overflow}


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def to_native(param, normalized):
    """Map LOM-normalized 0-1 -> native units via the param's min/max."""
    lo = float(param.get("min", 0.0))
    hi = float(param.get("max", 1.0))
    return lo + _clamp(float(normalized), 0.0, 1.0) * (hi - lo)


def to_normalized(param, native):
    """Map native units -> LOM-normalized 0-1 via the param's min/max (clamped)."""
    lo = float(param.get("min", 0.0))
    hi = float(param.get("max", 1.0))
    if hi == lo:
        return 0.0
    return _clamp((float(native) - lo) / (hi - lo), 0.0, 1.0)
