"""Pure helpers for transport / arrangement operations. No Live dependencies.

Like the other *_utils modules, these run server-side only (the Remote Script
in Live's embedded Python cannot import them). They coerce and validate
user-supplied values to the canonical forms the handler applies directly.
"""

from ableton_mcp_max.device_utils import coerce_on_value

# Cue-jump direction alias -> canonical "next" | "prev".
_CUE_DIR_CANON = {
    "next": "next",
    "forward": "next",
    "fwd": "next",
    "prev": "prev",
    "previous": "prev",
    "back": "prev",
    "backward": "prev",
}

# Time-signature denominators Live accepts.
_VALID_DENOMINATORS = (1, 2, 4, 8, 16)


def parse_time_signature(value):
    """Parse a time signature into a (numerator, denominator) int tuple.

    Accepts "4/4", "6/8", a (num, den) tuple/list, or numbers. Numerator must be
    1..99; denominator must be one of 1, 2, 4, 8, 16. Raises ValueError otherwise.
    """
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise ValueError(
                "Time signature must be 'num/den' (e.g. '4/4'); got %s" % (value,)
            )
        num, den = value[0], value[1]
    else:
        text = str(value).strip()
        if "/" not in text:
            raise ValueError(
                "Time signature must be 'num/den' (e.g. '4/4'); got '%s'" % (value,)
            )
        parts = text.split("/")
        if len(parts) != 2:
            raise ValueError(
                "Time signature must be 'num/den' (e.g. '4/4'); got '%s'" % (value,)
            )
        num, den = parts[0], parts[1]

    try:
        num = int(num)
        den = int(den)
    except (TypeError, ValueError):
        raise ValueError(
            "Time signature must be 'num/den' integers (e.g. '4/4'); got '%s'"
            % (value,)
        )

    if num < 1 or num > 99:
        raise ValueError(
            "Time signature numerator %d out of range (1..99)" % num
        )
    if den not in _VALID_DENOMINATORS:
        raise ValueError(
            "Time signature denominator %d invalid. Valid: %s"
            % (den, ", ".join(str(d) for d in _VALID_DENOMINATORS))
        )
    return (num, den)


def resolve_cue_direction(value):
    """Fold a cue-jump direction (case-insensitive) to canonical 'next' | 'prev'.
    Raises ValueError listing the valid forms."""
    lowered = str(value).strip().lower()
    if lowered in _CUE_DIR_CANON:
        return _CUE_DIR_CANON[lowered]
    raise ValueError(
        "Unknown cue direction '%s'. Valid: next, prev" % (value,)
    )


def coerce_song_time(value):
    """Coerce a song-position value to a non-negative float (in beats).
    Raises ValueError if negative or non-numeric."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError("Song position must be a number (beats); got '%s'" % (value,))
    if out < 0:
        raise ValueError("Song position must be >= 0; got %s" % (out,))
    return out


def coerce_jump_beats(value):
    """Coerce a jump-by amount to a float (negative allowed)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("Jump amount must be a number (beats); got '%s'" % (value,))


def coerce_loop_fields(enabled, start, length):
    """Build a dict of the arrangement-loop fields the caller actually provided
    (non-None), each coerced/validated. Raises ValueError if all are None or a
    provided value is out of range.

    - enabled -> bool (via coerce_on_value)
    - start   -> float >= 0
    - length  -> float > 0
    """
    out = {}
    if enabled is not None:
        out["enabled"] = coerce_on_value(enabled)
    if start is not None:
        s = float(start)
        if s < 0:
            raise ValueError("Loop start must be >= 0; got %s" % (s,))
        out["start"] = s
    if length is not None:
        ln = float(length)
        if ln <= 0:
            raise ValueError("Loop length must be > 0; got %s" % (ln,))
        out["length"] = ln
    if not out:
        raise ValueError(
            "Nothing to set: provide at least one of enabled, start, length."
        )
    return out


def coerce_punch_fields(punch_in, punch_out):
    """Build a dict of the punch flags the caller actually provided (non-None),
    each coerced to bool. Raises ValueError if both are None."""
    out = {}
    if punch_in is not None:
        out["punch_in"] = coerce_on_value(punch_in)
    if punch_out is not None:
        out["punch_out"] = coerce_on_value(punch_out)
    if not out:
        raise ValueError("Nothing to set: provide punch_in and/or punch_out.")
    return out
