"""Curated Ozone-12 mastering profiles: character bucket -> chain.

Pure module imported by server.py only. Each bucket maps to concrete Ozone
state-blob params, emitted as a {module_alias: {param_name: value}} dict in the
exact shape set_ozone_state accepts. PARAM_KEYS holds the real blob key strings
captured from a get_ozone_state spike (plan Task 0).

Reliability note: the Maximizer (always in the default Ozone chain) reliably
affects sound. The EQ shelves are best-effort - they shape tone only if the
Equalizer is in the user's active chain (ozone_state_utils.element_chain reads
it), and are harmless otherwise.

Loudness note: 'Target Loudness [dB]' is only the goal Master Assistant /
threshold learning aims for - writing it does NOT change output level (set -14,
rendered -8.9 LUFS). Output level follows the input trim (down) and the Maximizer
Gain (up). A mix that is already hotter than the target needs a negative
input_gain_db; find it by render: input_gain_db ~= target - measured LUFS.
"""

BUCKETS = ("transparent", "warm", "loud_club", "punchy", "bright")

# Semantic slot -> (module alias, real blob param name). From the Task 0 spike.
PARAM_KEYS = {
    "max_bypass":     ("MAX", "Bypass"),                        # False = module on
    "max_target":     ("MAX", "Target Loudness [dB]"),
    "max_ceiling":    ("MAX", "Margin"),                        # dB; 0 default, negative = headroom
    "max_isc":        ("MAX", "Prevent Intersample Clipping"),  # True = true-peak safe
    "max_gain":       ("MAX", "Gain"),                          # drive into the limiter, dB >= 0
    # Ozone input trim. With Input Lock on (default) only 'Locked' is used, so
    # input_trim_changes writes all three to work either way.
    "in_gain_locked": ("Gain Input", "Gain Input Locked"),
    "in_gain_left":   ("Gain Input", "Gain Input Left"),
    "in_gain_right":  ("Gain Input", "Gain Input Right"),
    "eq_bypass":      ("EQ", "Bypass"),                         # False = module on
    "eq_low_enable":  ("EQ", "Band 1 Enable"),                 # ~100 Hz low shelf
    "eq_low_gain":    ("EQ", "Band 1 Gain"),
    "eq_high_enable": ("EQ", "Band 8 Enable"),                 # ~16 kHz high shelf
    "eq_high_gain":   ("EQ", "Band 8 Gain"),
}

# Per-bucket EQ shelf gains (dB). Each bucket has a distinct fingerprint. Tonal
# EQ is best-effort (see module docstring); the Maximizer loudness/ceiling is the
# reliable part of every chain.
BUCKET_SHAPES = {
    "transparent": {"eq_low_gain": 0.0,  "eq_high_gain": 0.0},
    "warm":        {"eq_low_gain": 1.0,  "eq_high_gain": -0.5},
    "loud_club":   {"eq_low_gain": 0.5,  "eq_high_gain": 0.5},
    "punchy":      {"eq_low_gain": -0.5, "eq_high_gain": 0.5},
    "bright":      {"eq_low_gain": -0.5, "eq_high_gain": 1.5},
}


def _put(chain, slot, value):
    """Place value at PARAM_KEYS[slot] into the chain (value None -> skip)."""
    if value is None:
        return
    alias, pname = PARAM_KEYS[slot]
    chain.setdefault(alias, {})[pname] = value


def input_trim_changes(db, chain=None):
    """set_ozone_state changes for an Ozone input trim of `db` dB (negative =
    quieter), written to the locked and per-side fields alike."""
    chain = {} if chain is None else chain
    for slot in ("in_gain_locked", "in_gain_left", "in_gain_right"):
        _put(chain, slot, float(db))
    return chain


def build_chain(bucket, target_lufs, true_peak):
    """Build a set_ozone_state-shaped changes dict for a character bucket.

    Maximizer settings (enable, target, ceiling, true-peak safety) are always
    emitted - they are the reliable part of the chain. target_lufs passes through
    to the Maximizer target (the auto-learn goal only - it does not set output
    loudness; see the module docstring); true_peak sets the Margin (ceiling). EQ shelves are emitted only for a nonzero bucket gain, each
    paired with enabling its band. Raises KeyError for an unknown bucket.
    """
    shape = BUCKET_SHAPES[bucket]  # KeyError on unknown bucket (tested)
    chain = {}
    # Maximizer - unconditional (always in the default Ozone chain).
    _put(chain, "max_bypass", False)
    _put(chain, "max_target", float(target_lufs))
    _put(chain, "max_ceiling", float(true_peak))
    _put(chain, "max_isc", True)
    # EQ shelves - best-effort, only when the bucket asks for a nonzero gain.
    low = float(shape["eq_low_gain"])
    high = float(shape["eq_high_gain"])
    if low != 0.0:
        _put(chain, "eq_bypass", False)
        _put(chain, "eq_low_enable", True)
        _put(chain, "eq_low_gain", low)
    if high != 0.0:
        _put(chain, "eq_bypass", False)
        _put(chain, "eq_high_enable", True)
        _put(chain, "eq_high_gain", high)
    return chain
