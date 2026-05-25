"""Pure helpers for change-listener (observer) handling. No Live dependencies.

Live's LOM exposes change observation as a push API (obj.add_*_listener(cb)).
This MCP is request/response, so the Remote Script attaches the listener and
buffers events; these helpers run on the SERVER and turn a friendly target spec
(scope + property + selectors) into a canonical *descriptor* the Remote Script
can act on without any name resolution of its own.

Descriptor shape (all values JSON-safe):
    {
        "scope": "transport"|"mixer"|"clip"|"device",
        "property": <canonical>,
        "target_kind": "song"|"song_view"|"track"|"track_mixer"|"clip"
                        |"clip_slot"|"device_param",
        "listener_method": "add_<x>_listener",
        "remove_method": "remove_<x>_listener",
        "readback": <attr name to read in the callback> | None,
        "mixer_sub": "volume"|"panning" | None,   # only for target_kind track_mixer
        "selectors": {track_index, track_type, device_index,
                      parameter_index, clip_index, scene_index},  # only those used
    }

Device-parameter resolution (identifier -> parameter_index) happens in server.py
against the live parameter list before build_descriptor is called.
"""

from ableton_mcp_max.mixer_utils import validate_property as _validate_mixer_property

_SCOPES = ("transport", "mixer", "clip", "device")

# Per-scope alias -> canonical property (all lowercase).
_PROPERTY_ALIASES = {
    "transport": {
        "is_playing": "is_playing", "playing": "is_playing", "play": "is_playing",
        "current_song_time": "current_song_time", "position": "current_song_time",
        "song_time": "current_song_time", "time": "current_song_time",
        "tempo": "tempo", "bpm": "tempo",
        "metronome": "metronome", "metro": "metronome", "click": "metronome",
        "record_mode": "record_mode", "arrangement_record": "record_mode",
        "session_record": "session_record",
        "loop": "loop",
    },
    "mixer": {
        "volume": "volume", "vol": "volume",
        "pan": "pan", "panning": "pan",
        "mute": "mute",
        "solo": "solo",
        "arm": "arm", "record_arm": "arm", "rec": "arm",
    },
    "clip": {
        "playing_status": "playing_status", "playing": "playing_status",
        "is_playing": "playing_status", "status": "playing_status",
        "name": "name",
        "notes": "notes",
        "has_clip": "has_clip", "slot": "has_clip",
        "selected_scene": "selected_scene", "scene": "selected_scene",
    },
    "device": {
        "value": "value", "parameter": "value", "param": "value",
    },
}

# canonical property -> descriptor spec (target_kind, listener stem, readback, mixer_sub).
# listener_method = "add_<stem>_listener"; remove_method = "remove_<stem>_listener".
_SPEC = {
    "transport": {
        "is_playing":         ("song", "is_playing", "is_playing", None),
        "current_song_time":  ("song", "current_song_time", "current_song_time", None),
        "tempo":              ("song", "tempo", "tempo", None),
        "metronome":          ("song", "metronome", "metronome", None),
        "record_mode":        ("song", "record_mode", "record_mode", None),
        "session_record":     ("song", "session_record", "session_record", None),
        "loop":               ("song", "loop", "loop", None),
    },
    "mixer": {
        "volume": ("track_mixer", "value", "value", "volume"),
        "pan":    ("track_mixer", "value", "value", "panning"),
        "mute":   ("track", "mute", "mute", None),
        "solo":   ("track", "solo", "solo", None),
        "arm":    ("track", "arm", "arm", None),
    },
    "clip": {
        "playing_status": ("clip", "playing_status", "is_playing", None),
        "name":           ("clip", "name", "name", None),
        "notes":          ("clip", "notes", None, None),
        "has_clip":       ("clip_slot", "has_clip", "has_clip", None),
        "selected_scene": ("song_view", "selected_scene", "selected_scene", None),
    },
    "device": {
        "value": ("device_param", "value", "value", None),
    },
}


def normalize_scope(scope):
    """Fold scope to one of transport|mixer|clip|device (case-insensitive)."""
    lowered = str(scope).strip().lower()
    if lowered in _SCOPES:
        return lowered
    raise ValueError(
        "Unknown scope '%s'. Valid: %s" % (scope, ", ".join(_SCOPES))
    )


def normalize_listener_property(scope, prop):
    """Fold a property/alias to its canonical form for the given scope."""
    aliases = _PROPERTY_ALIASES[scope]
    lowered = str(prop).strip().lower()
    if lowered in aliases:
        return aliases[lowered]
    valid = ", ".join(sorted(set(aliases.values())))
    raise ValueError(
        "Unknown %s property '%s'. Valid: %s" % (scope, prop, valid)
    )


def _require(selectors, key, scope, prop):
    if selectors.get(key) is None:
        raise ValueError(
            "%s listener for '%s' requires %s" % (scope, prop, key)
        )
    return selectors[key]


def build_descriptor(scope, prop, track_index=None, track_type="regular",
                     device_index=None, parameter_index=None,
                     clip_index=None, scene_index=None):
    """Validate a listener target and return its canonical descriptor.

    Raises ValueError on an unknown scope/property, a missing required selector,
    or an unsupported track-type/property combination (e.g. arm on a return).
    `parameter_index` must already be resolved (server-side) for device scope.
    """
    scope = normalize_scope(scope)
    canonical = normalize_listener_property(scope, prop)
    target_kind, stem, readback, mixer_sub = _SPEC[scope][canonical]

    sel_in = {
        "track_index": track_index, "track_type": track_type,
        "device_index": device_index, "parameter_index": parameter_index,
        "clip_index": clip_index, "scene_index": scene_index,
    }
    selectors = {}

    if target_kind in ("track", "track_mixer", "clip", "clip_slot", "device_param"):
        selectors["track_index"] = int(_require(sel_in, "track_index", scope, canonical))
        selectors["track_type"] = str(track_type or "regular").strip().lower()

    # Mixer track-type asymmetry (no arm on return/master, etc.) — reuse mixer rules.
    if scope == "mixer":
        _validate_mixer_property(selectors["track_type"], canonical)

    if target_kind in ("clip", "clip_slot"):
        selectors["clip_index"] = int(_require(sel_in, "clip_index", scope, canonical))

    if target_kind == "device_param":
        selectors["device_index"] = int(_require(sel_in, "device_index", scope, canonical))
        selectors["parameter_index"] = int(_require(sel_in, "parameter_index", scope, canonical))

    descriptor = {
        "scope": scope,
        "property": canonical,
        "target_kind": target_kind,
        "listener_method": "add_%s_listener" % stem,
        "remove_method": "remove_%s_listener" % stem,
        "readback": readback,
        "mixer_sub": mixer_sub,
        "selectors": selectors,
    }
    return descriptor


def coerce_max_events(n):
    """Clamp a poll cap to >= 1; None means 'all'."""
    if n is None:
        return None
    n = int(n)
    return n if n >= 1 else 1


def needs_device_resolution(scope, prop):
    """True if this target is a device parameter (server must resolve the
    parameter identifier to an index before build_descriptor)."""
    return normalize_scope(scope) == "device"
