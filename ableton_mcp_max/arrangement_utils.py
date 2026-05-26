"""Pure helpers for arrangement authoring (cue points + arrangement clips).

No Live dependencies — server-side only, like the other *_utils modules. The
Remote Script runs in Live's own interpreter and cannot import this; the server
coerces/validates here and sends already-resolved values to the handler.
"""


def coerce_time(value):
    """Coerce an arrangement time to a non-negative float (in beats).
    Raises ValueError if negative or non-numeric."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError("Time must be a number (beats); got '%s'" % (value,))
    if out < 0:
        raise ValueError("Time must be >= 0; got %s" % (out,))
    return out


def coerce_index(value):
    """Coerce an index to a non-negative int. Raises ValueError otherwise."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer; got '%s'" % (value,))
    if out < 0:
        raise ValueError("Index must be >= 0; got %s" % (out,))
    return out


def cue_exists_at(cue_times, time, epsilon=1e-6):
    """Return (exists, index) for whether a cue sits at `time` within epsilon.

    `cue_times` is an ordered list of floats (cue point times in beats); index
    is None when no cue matches.
    """
    for i, t in enumerate(cue_times):
        if abs(float(t) - float(time)) <= epsilon:
            return (True, i)
    return (False, None)
