"""Pure helpers for transport / arrangement operations. No Live dependencies.

Like the other *_utils modules, these run server-side only (the Remote Script
in Live's embedded Python cannot import them). They coerce and validate
user-supplied values to the canonical forms the handler applies directly.
"""

from ableton_mcp_max.device_utils import coerce_on_value
from ableton_mcp_max.clip_utils import QUANTIZE_GRID_MAP

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


# --- Phase 10: global feel / quantization ---------------------------------

# Friendly name -> Live.Song.Quantization int (clip_trigger_quantization).
# This enum spans bar-level values (unlike RecordingQuantization). Ordering is
# the standard Live 11 Quantization enum; CONFIRM live before trusting the names
# (the int path always works regardless).
CLIP_TRIGGER_QUANTIZATION_MAP = {
    "none": 0,
    "8_bars": 1,
    "4_bars": 2,
    "2_bars": 3,
    "1_bar": 4,
    "1/2": 5,
    "1/2t": 6,
    "1/4": 7,
    "1/4t": 8,
    "1/8": 9,
    "1/8t": 10,
    "1/16": 11,
    "1/16t": 12,
    "1/32": 13,
}

_NUDGE_DIRECTIONS = ("up", "down")


def coerce_unit_float(value, label="value"):
    """Coerce to a float clamped to 0.0-1.0. Raises ValueError if non-numeric."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number (0.0-1.0); got '%s'" % (label, value))
    if out < 0.0:
        out = 0.0
    if out > 1.0:
        out = 1.0
    return out


def resolve_clip_trigger_quantization(value):
    """Map an int (pass-through) or a friendly name to the
    Live.Song.Quantization int for clip_trigger_quantization.

    Ints are accepted directly (0..13). Names fold via
    CLIP_TRIGGER_QUANTIZATION_MAP. Raises ValueError otherwise.
    """
    if isinstance(value, bool):
        raise ValueError("Quantization must be an int or name; got a bool")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    key = str(value).strip().lower()
    if key in CLIP_TRIGGER_QUANTIZATION_MAP:
        return CLIP_TRIGGER_QUANTIZATION_MAP[key]
    raise ValueError(
        "Unknown clip-trigger quantization '%s'. Available: %s (or an int 0-13)"
        % (value, ", ".join(CLIP_TRIGGER_QUANTIZATION_MAP.keys()))
    )


def resolve_midi_recording_quantization(value):
    """Map an int (pass-through) or a friendly grid name to the
    Live.Song.RecordingQuantization int for midi_recording_quantization.

    Reuses clip_utils.QUANTIZE_GRID_MAP (same enum, live-confirmed:
    none=0, 1/4=1, 1/8=2, ...). Ints accepted directly. Raises ValueError otherwise.
    """
    if isinstance(value, bool):
        raise ValueError("Quantization must be an int or name; got a bool")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    key = str(value).strip().lower()
    if key in QUANTIZE_GRID_MAP:
        return QUANTIZE_GRID_MAP[key]
    raise ValueError(
        "Unknown MIDI recording quantization '%s'. Available: %s (or an int)"
        % (value, ", ".join(QUANTIZE_GRID_MAP.keys()))
    )


def normalize_nudge_direction(value):
    """Fold a nudge direction (case-insensitive) to 'up' | 'down'.
    Raises ValueError otherwise."""
    key = str(value).strip().lower()
    if key in _NUDGE_DIRECTIONS:
        return key
    raise ValueError(
        "Unknown nudge direction '%s'. Valid: up, down" % (value,)
    )


# --- Phase 11: capture & recording ----------------------------------------

# CaptureDestination / CaptureMode member NAMES (Live.Song.CaptureDestination /
# Live.Song.CaptureMode). The enum INTEGER values are undocumented in the LOM, so
# the server validates the name and the Remote Script resolves it to the Live enum
# via getattr — keeping the int source-of-truth in Live itself.
CAPTURE_DESTINATION_NAMES = ("auto", "session", "arrangement")
CAPTURE_MODE_NAMES = ("all",)


def resolve_capture_destination(value):
    """Validate a capture destination name (case-insensitive) and return the
    canonical lowercase name. None -> 'auto'. Raises ValueError otherwise."""
    if value is None:
        return "auto"
    key = str(value).strip().lower()
    if key in CAPTURE_DESTINATION_NAMES:
        return key
    raise ValueError(
        "Unknown capture destination '%s'. Valid: %s"
        % (value, ", ".join(CAPTURE_DESTINATION_NAMES))
    )


def resolve_capture_mode(value):
    """Validate a capture mode name (case-insensitive) and return the canonical
    lowercase name. None -> 'all'. Raises ValueError otherwise."""
    if value is None:
        return "all"
    key = str(value).strip().lower()
    if key in CAPTURE_MODE_NAMES:
        return key
    raise ValueError(
        "Unknown capture mode '%s'. Valid: %s"
        % (value, ", ".join(CAPTURE_MODE_NAMES))
    )


def coerce_record_length(value):
    """Coerce a session-record length (in beats) to a positive float, or None to
    omit (Live then uses its open-ended default). Raises ValueError if non-numeric
    or <= 0."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            "Record length must be a number (beats) or omitted; got '%s'" % (value,)
        )
    if out <= 0:
        raise ValueError("Record length must be > 0; got %s" % (out,))
    return out
