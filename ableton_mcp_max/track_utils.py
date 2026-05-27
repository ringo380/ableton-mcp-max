"""Pure helpers for track lifecycle (create/delete/duplicate).

No Live dependencies — server-side only, like the other *_utils modules. The
Remote Script runs in Live's own interpreter and cannot import this; the server
coerces/validates here and sends already-resolved ints to the handler.
"""


def coerce_create_index(value):
    """Coerce a create-track index. None or -1 mean 'append at end'; any value
    >= 0 is an insert position. Raises ValueError for < -1 or non-integers."""
    if value is None:
        return -1
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer or None; got '%s'" % (value,))
    if out < -1:
        raise ValueError("Index must be >= -1 (-1 = end); got %s" % (out,))
    return out


def coerce_track_index(value):
    """Coerce a delete/duplicate track index to a non-negative int.
    Raises ValueError otherwise."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer; got '%s'" % (value,))
    if out < 0:
        raise ValueError("Index must be >= 0; got %s" % (out,))
    return out
