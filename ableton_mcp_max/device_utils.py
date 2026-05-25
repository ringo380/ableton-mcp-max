"""Pure helpers for device/rack operations. No Live dependencies.

Like the other *_utils modules, these run server-side only (the Remote Script
in Live's embedded Python cannot import them). They resolve user-supplied
names/indices/booleans to canonical values that the handler can apply directly.
"""

# Chain property canonical name -> set of aliases (all lowercase).
_CHAIN_ALIASES = {
    "mute": {"mute"},
    "solo": {"solo"},
    "volume": {"volume", "vol"},
    "panning": {"panning", "pan"},
}

# Chain properties that take a boolean value vs a clamped float.
_CHAIN_BOOL = {"mute", "solo"}
_CHAIN_FLOAT = {"volume", "panning"}


def resolve_device_index(devices, identifier):
    """Resolve a device identifier (int index, numeric string, or name) to its
    integer index within `devices` (a list of dicts with 'index' and 'name'
    keys, as returned by get_track_info / get_device_info).

    Raises ValueError if it can't be resolved.
    """
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        idx = int(identifier)
        if idx < 0 or idx >= len(devices):
            raise ValueError(
                "Device index %d out of range (0..%d)" % (idx, len(devices) - 1)
            )
        return idx

    for d in devices:
        if d.get("name") == identifier:
            return d["index"]

    lowered = str(identifier).lower()
    for d in devices:
        if str(d.get("name", "")).lower() == lowered:
            return d["index"]

    names = ", ".join(str(d.get("name", "")) for d in devices)
    raise ValueError("Device '%s' not found. Available: %s" % (identifier, names))


def resolve_macro(macros, identifier):
    """Resolve a macro identifier to the underlying device-parameter index.

    `macros` is a list of dicts with 'index' (the device-parameter index) and
    'name' (e.g. 'Macro 1') keys. Accepts:
      - an int / numeric string: treated as a 1-based macro number ("Macro 3" -> 3)
      - an exact or case-insensitive macro name ("Macro 3", "macro 3")

    Raises ValueError if it can't be resolved.
    """
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        num = int(identifier)
        target = "macro %d" % num
        for m in macros:
            if str(m.get("name", "")).lower() == target:
                return m["index"]
        names = ", ".join(str(m.get("name", "")) for m in macros)
        raise ValueError(
            "Macro number %d not found. Available: %s" % (num, names)
        )

    lowered = str(identifier).strip().lower()
    for m in macros:
        if str(m.get("name", "")).lower() == lowered:
            return m["index"]

    names = ", ".join(str(m.get("name", "")) for m in macros)
    raise ValueError("Macro '%s' not found. Available: %s" % (identifier, names))


def normalize_chain_property(name):
    """Fold a chain property name/alias (case-insensitive) to canonical form.
    Raises ValueError listing the canonical names if unrecognized."""
    lowered = str(name).strip().lower()
    for canonical, aliases in _CHAIN_ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown chain property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_CHAIN_ALIASES.keys())))
    )


def validate_chain_property(canonical_property):
    """Confirm a canonical chain property is one we support. Returns it."""
    if canonical_property not in _CHAIN_BOOL and canonical_property not in _CHAIN_FLOAT:
        raise ValueError(
            "Chain property '%s' not supported. Supported: %s"
            % (canonical_property,
               ", ".join(sorted(_CHAIN_BOOL | _CHAIN_FLOAT)))
        )
    return canonical_property


def coerce_chain_value(canonical_property, value):
    """Coerce a chain property value to the type the handler expects:
    bool for mute/solo, float for volume/panning."""
    if canonical_property in _CHAIN_BOOL:
        return coerce_on_value(value)
    return float(value)


def coerce_on_value(value):
    """Coerce a bool-ish input to True/False.

    Accepts real bools, 0/1, and common string forms (on/off, true/false,
    yes/no, 1/0). Raises ValueError on anything else.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("on", "true", "yes", "1", "enable", "enabled"):
            return True
        if lowered in ("off", "false", "no", "0", "disable", "disabled"):
            return False
    raise ValueError(
        "Cannot interpret '%s' as on/off. Use true/false, on/off, 1/0." % (value,)
    )
