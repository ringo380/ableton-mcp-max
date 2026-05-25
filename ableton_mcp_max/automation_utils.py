"""Pure helpers for automation-envelope handling. No Live dependencies.

The server uses these to normalize targets and validate breakpoints before
sending already-resolved values to the Remote Script (which runs in Live's own
interpreter and cannot import this module)."""

from ableton_mcp_max.mixer_utils import normalize_property

_CLIP_LOCATIONS = ("session", "arrangement")
_TARGET_TYPES = ("device", "mixer")
# Mixer properties that can host automation (canonical names from mixer_utils).
_MIXER_AUTOMATABLE = ("volume", "pan", "send")


def normalize_clip_location(loc):
    """Fold clip location to 'session'|'arrangement' (case-insensitive)."""
    lowered = str(loc).strip().lower()
    if lowered in _CLIP_LOCATIONS:
        return lowered
    raise ValueError(
        "Unknown clip_location '%s'. Valid: session, arrangement" % loc
    )


def normalize_target_type(t):
    """Fold target type to 'device'|'mixer' (case-insensitive)."""
    lowered = str(t).strip().lower()
    if lowered in _TARGET_TYPES:
        return lowered
    raise ValueError(
        "Unknown target_type '%s'. Valid: device, mixer" % t
    )


def normalize_mixer_target(mixer_property, send_index):
    """Normalize a mixer automation target. Returns (canonical, send_index).
    Only volume/pan/send are automatable; 'send' requires send_index >= 0."""
    canonical = normalize_property(mixer_property)  # reuse mixer aliases
    if canonical not in _MIXER_AUTOMATABLE:
        raise ValueError(
            "Mixer property '%s' is not automatable. Valid: volume, pan, send"
            % mixer_property
        )
    if canonical == "send" and (send_index is None or send_index < 0):
        raise ValueError("mixer_property 'send' requires send_index >= 0")
    return canonical, (send_index if canonical == "send" else -1)


def coerce_resolution(n):
    """Sample count for a read; clamp to >= 1."""
    n = int(n)
    return n if n >= 1 else 1


def coerce_time(t):
    """Coerce a non-negative time (beats)."""
    v = float(t)
    if v < 0:
        raise ValueError("time must be >= 0")
    return v


def coerce_duration(d):
    """Coerce a non-negative duration (beats); 0 = single breakpoint."""
    v = float(d)
    if v < 0:
        raise ValueError("duration must be >= 0")
    return v


def coerce_value(v):
    """Coerce an envelope value to float (clamping happens in Live)."""
    return float(v)


def normalize_breakpoints(points, time, value, default_duration):
    """Build a validated list of breakpoints from EITHER a `points` list OR the
    single (time, value, duration) form. Each entry -> {time, value, duration}.
    Raises ValueError on an empty result, a missing time/value, or a negative
    time/duration."""
    if points is None:
        if time is None or value is None:
            raise ValueError(
                "set_automation requires either `points` or both `time` and `value`"
            )
        return [{
            "time": coerce_time(time),
            "value": coerce_value(value),
            "duration": coerce_duration(default_duration),
        }]
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        raise ValueError("`points` must be a non-empty list of breakpoints")
    out = []
    for i, p in enumerate(points):
        if "time" not in p or "value" not in p:
            raise ValueError(
                "breakpoint %d missing 'time' or 'value': %r" % (i, p)
            )
        out.append({
            "time": coerce_time(p["time"]),
            "value": coerce_value(p["value"]),
            "duration": coerce_duration(p.get("duration", default_duration)),
        })
    return out
