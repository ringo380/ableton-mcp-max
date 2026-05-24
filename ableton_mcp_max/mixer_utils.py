"""Pure helpers for mixer property handling. No Live dependencies."""

# Canonical property name -> set of aliases (all lowercase).
_ALIASES = {
    "volume": {"volume", "vol"},
    "pan": {"pan", "panning"},
    "mute": {"mute"},
    "solo": {"solo"},
    "arm": {"arm", "record_arm", "rec"},
    "send": {"send"},
    "crossfade_assign": {"crossfade_assign", "crossfade", "xfade"},
}

# Which canonical properties each track type supports.
_SUPPORTED = {
    "regular": {"volume", "pan", "mute", "solo", "arm", "send", "crossfade_assign"},
    "return": {"volume", "pan", "mute", "solo", "send", "crossfade_assign"},
    "master": {"volume", "pan"},
}


def normalize_property(name):
    """Fold an input property name/alias (case-insensitive) to its canonical form.
    Raises ValueError listing the canonical names if unrecognized."""
    lowered = str(name).strip().lower()
    for canonical, aliases in _ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown mixer property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_ALIASES.keys())))
    )


def validate_property(track_type, canonical_property):
    """Ensure `canonical_property` is supported for `track_type`
    ('regular'|'return'|'master'). Raises ValueError otherwise."""
    if track_type not in _SUPPORTED:
        raise ValueError(
            "Unknown track_type '%s'. Valid: regular, return, master" % track_type
        )
    if canonical_property not in _SUPPORTED[track_type]:
        raise ValueError(
            "Property '%s' not supported on %s tracks. Supported: %s"
            % (canonical_property, track_type,
               ", ".join(sorted(_SUPPORTED[track_type])))
        )
    return canonical_property
