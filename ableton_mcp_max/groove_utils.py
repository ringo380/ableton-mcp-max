"""Pure swing/groove helpers. Imported by server.py only (never the Remote
Script). Resolves a user-facing swing amount to a canonical fraction and bakes
off-beat delay into note start-times. See issue #27."""

_GRID_STEPS = {"1/8": 0.5, "1/16": 0.25}


def resolve_swing(amount):
    """Map a swing `amount` to a canonical fraction in [0.0, 1.0].

    - number in [0.0, 1.0]      -> direct fraction (0 = straight, 1 = max).
    - number > 1.0, or "<n>%"   -> MPC-style percent: (percent - 50) / 50.
    Result is clamped to [0.0, 1.0]. Raises ValueError on non-numeric input.
    """
    is_percent = False
    if isinstance(amount, str):
        s = amount.strip()
        if s.endswith("%"):
            is_percent = True
            s = s[:-1].strip()
        try:
            value = float(s)
        except ValueError:
            raise ValueError("swing amount must be a number or percent string, got %r" % amount)
    else:
        try:
            value = float(amount)
        except (TypeError, ValueError):
            raise ValueError("swing amount must be a number, got %r" % (amount,))

    if is_percent or value > 1.0:
        fraction = (value - 50.0) / 50.0
    else:
        fraction = value
    return max(0.0, min(1.0, fraction))


def grid_to_step(grid):
    """Beats per grid step. Accepts '1/8' (0.5) or '1/16' (0.25)."""
    try:
        return _GRID_STEPS[grid]
    except KeyError:
        raise ValueError("grid must be one of %s, got %r" % (sorted(_GRID_STEPS), grid))


def swing_notes(notes, step, fraction, tolerance=None):
    """Delay off-beat notes by `fraction * step/2`. Pure: returns new dicts.

    A note at start_time t is on grid step k = round(t/step). If it sits within
    `tolerance` of that step and k is odd (an off-beat), it is delayed; all other
    notes pass through unchanged. `tolerance` defaults to step*0.5 (snap every
    note - the predictable default for on-grid generated parts).
    """
    if tolerance is None:
        tolerance = step * 0.5
    delay = fraction * (step / 2.0)
    out = []
    for n in notes:
        m = dict(n)
        t = float(n.get("start_time", 0.0))
        k = round(t / step)
        if abs(t - k * step) <= tolerance and k % 2 == 1:
            m["start_time"] = round(t + delay, 6)
        out.append(m)
    return out
