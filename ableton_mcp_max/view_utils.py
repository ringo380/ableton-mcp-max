"""Pure helpers for view/selection and track folding (Phase 10).

No Live dependencies — server-side only, like the other *_utils modules. The
Remote Script runs in Live's own interpreter and cannot import this; the server
coerces/validates here and sends already-resolved values to the handler.
"""

_TRACK_TYPES = ("regular", "return", "master")


def normalize_track_type(value):
    """Fold a track-type label (case-insensitive) to 'regular' | 'return' |
    'master'. None defaults to 'regular'. Raises ValueError otherwise."""
    if value is None:
        return "regular"
    key = str(value).strip().lower()
    if key in _TRACK_TYPES:
        return key
    raise ValueError(
        "Unknown track_type '%s'. Valid: regular, return, master" % (value,)
    )


def coerce_index(value):
    """Coerce an index to a non-negative int. Raises ValueError otherwise."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer; got '%s'" % (value,))
    if out < 0:
        raise ValueError("Index must be >= 0; got %s" % (out,))
    return out
