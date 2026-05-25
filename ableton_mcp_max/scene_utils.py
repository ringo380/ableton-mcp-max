"""Pure helpers for scene operations. No Live dependencies.

Server-side only (the Remote Script in Live's embedded Python cannot import
them). They fold property aliases and coerce values to the canonical forms the
handler applies directly to a Live.Scene.
"""

from ableton_mcp_max.device_utils import coerce_on_value
from ableton_mcp_max.transport_utils import parse_time_signature

# Canonical scene property -> set of aliases (all lowercase, spaces->underscores).
_SCENE_ALIASES = {
    "color": {"color", "colour"},
    "tempo": {"tempo", "bpm"},
    "tempo_enabled": {"tempo_enabled", "tempo_on", "tempo_enable"},
    "time_signature": {"time_signature", "time_sig", "signature", "sig"},
}

# Tempo clamp (Live's session tempo range).
_TEMPO_MIN = 20.0
_TEMPO_MAX = 999.0


def normalize_scene_property(name):
    """Fold a scene property name/alias (case-insensitive, spaces->underscores)
    to its canonical form. Raises ValueError listing the canonical names."""
    lowered = str(name).strip().lower().replace(" ", "_")
    for canonical, aliases in _SCENE_ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown scene property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_SCENE_ALIASES.keys())))
    )


def coerce_scene_value(canonical_property, value):
    """Coerce a scene property value to the type the handler expects:
    - tempo_enabled -> bool (via coerce_on_value)
    - tempo         -> float, clamped to 20..999
    - color         -> int
    - time_signature-> (numerator, denominator) int tuple
    """
    if canonical_property == "tempo_enabled":
        return coerce_on_value(value)
    if canonical_property == "tempo":
        out = float(value)
        if out < _TEMPO_MIN:
            out = _TEMPO_MIN
        if out > _TEMPO_MAX:
            out = _TEMPO_MAX
        return out
    if canonical_property == "color":
        return int(value)
    if canonical_property == "time_signature":
        return parse_time_signature(value)
    raise ValueError(
        "Unknown scene property '%s'. Valid: %s"
        % (canonical_property, ", ".join(sorted(_SCENE_ALIASES.keys())))
    )
