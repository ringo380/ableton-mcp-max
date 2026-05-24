"""Pure helpers for track routing. No Live dependencies."""

_ALIASES = {
    "input_type": {"input_type", "in_type", "input"},
    "input_channel": {"input_channel", "in_channel", "in_chan"},
    "output_type": {"output_type", "out_type", "output"},
    "output_channel": {"output_channel", "out_channel", "out_chan"},
    "monitor": {"monitor", "monitoring", "current_monitoring_state"},
}

# Live exposes input + output routing on all track types (return/master can take
# external input and route output to hardware). Only input monitoring is
# regular-track-only -- return/master raise "no monitoring state" on access.
_ROUTING = {"input_type", "input_channel", "output_type", "output_channel"}
_SUPPORTED = {
    "regular": _ROUTING | {"monitor"},
    "return": set(_ROUTING),
    "master": set(_ROUTING),
}


def normalize_routing_property(name):
    """Fold an input routing property name/alias (case-insensitive, spaces ->
    underscores) to its canonical form. Raises ValueError if unrecognized."""
    lowered = str(name).strip().lower().replace(" ", "_")
    for canonical, aliases in _ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown routing property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_ALIASES.keys())))
    )


def validate_routing_property(track_type, canonical_property):
    """Ensure `canonical_property` is supported for `track_type`. Raises ValueError."""
    if track_type not in _SUPPORTED:
        raise ValueError(
            "Unknown track_type '%s'. Valid: regular, return, master" % track_type
        )
    if canonical_property not in _SUPPORTED[track_type]:
        raise ValueError(
            "Routing property '%s' not supported on %s tracks. Supported: %s"
            % (canonical_property, track_type,
               ", ".join(sorted(_SUPPORTED[track_type])))
        )
    return canonical_property


def resolve_routing_choice(available, identifier):
    """Match `identifier` (display_name str, or int/numeric identifier) against
    a list of {display_name, identifier} dicts. Returns the matched dict.
    Raises ValueError listing the available display names."""
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        ident = int(identifier)
        for c in available:
            if c.get("identifier") == ident:
                return c
    else:
        lowered = str(identifier).strip().lower()
        for c in available:
            if str(c.get("display_name", "")).lower() == lowered:
                return c
    names = ", ".join(str(c.get("display_name", "")) for c in available)
    raise ValueError("Routing choice '%s' not found. Available: %s" % (identifier, names))
