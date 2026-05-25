"""Pure helpers for clip property handling and MIDI quantization. No Live deps."""

# Canonical clip property -> set of aliases (all lowercase, spaces->underscores).
_ALIASES = {
    "looping": {"looping", "loop", "loop_on"},
    "loop_start": {"loop_start", "loopstart"},
    "loop_end": {"loop_end", "loopend"},
    "start_marker": {"start_marker", "start", "startmarker"},
    "end_marker": {"end_marker", "end", "endmarker"},
    "signature_numerator": {"signature_numerator", "sig_numerator", "numerator"},
    "signature_denominator": {"signature_denominator", "sig_denominator", "denominator"},
    "warping": {"warping", "warp", "warp_on"},
    "warp_mode": {"warp_mode", "warpmode"},
    "gain": {"gain"},
    "pitch_coarse": {"pitch_coarse", "pitch", "transpose", "pitch_semitones"},
    "pitch_fine": {"pitch_fine", "detune", "pitch_cents"},
}

# Properties valid on each clip kind. Audio clips additionally expose
# warping/warp_mode/gain/pitch_*; those raise on MIDI clips.
_COMMON = {
    "looping", "loop_start", "loop_end", "start_marker", "end_marker",
    "signature_numerator", "signature_denominator",
}
_AUDIO_ONLY = {"warping", "warp_mode", "gain", "pitch_coarse", "pitch_fine"}
_CLIP_KIND_SUPPORT = {
    "midi": set(_COMMON),
    "audio": _COMMON | _AUDIO_ONLY,
}

# Properties coerced to bool / int (others float).
_BOOL_PROPS = {"looping", "warping"}
_INT_PROPS = {
    "signature_numerator", "signature_denominator", "warp_mode",
    "pitch_coarse", "pitch_fine",
}
# Pure (live-state-independent) clamps: prop -> (min, max).
_CLAMPS = {
    "gain": (0.0, 1.0),
    "pitch_coarse": (-48, 48),
    "pitch_fine": (-50, 50),
}

# Friendly grid name -> Live.Song.RecordingQuantization enum int.
# VALUES MUST BE VERIFIED LIVE -- the RecordingQuantization member ordering can
# differ across Live versions. These follow the documented Live 11 ordering.
QUANTIZE_GRID_MAP = {
    "none": 0,
    "1/4": 1,
    "1/4t": 2,
    "1/8": 3,
    "1/8t": 4,
    "1/8+1/8t": 5,
    "1/16": 6,
    "1/16t": 7,
    "1/16+1/16t": 8,
    "1/32": 9,
}


def normalize_clip_property(name):
    """Fold a clip property name/alias (case-insensitive, spaces->underscores)
    to its canonical form. Raises ValueError listing canonical names."""
    lowered = str(name).strip().lower().replace(" ", "_")
    for canonical, aliases in _ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown clip property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_ALIASES.keys())))
    )


def validate_clip_property(clip_kind, canonical_property):
    """Ensure `canonical_property` applies to `clip_kind` ('midi'|'audio').
    Raises ValueError otherwise (audio-only props on a MIDI clip, etc.)."""
    if clip_kind not in _CLIP_KIND_SUPPORT:
        raise ValueError(
            "Unknown clip_kind '%s'. Valid: midi, audio" % clip_kind
        )
    if canonical_property not in _CLIP_KIND_SUPPORT[clip_kind]:
        if canonical_property in _AUDIO_ONLY:
            raise ValueError(
                "Property '%s' is audio-only; not valid on a MIDI clip."
                % canonical_property
            )
        raise ValueError(
            "Property '%s' not supported on %s clips. Supported: %s"
            % (canonical_property, clip_kind,
               ", ".join(sorted(_CLIP_KIND_SUPPORT[clip_kind])))
        )
    return canonical_property


def coerce_clip_value(canonical_property, value):
    """Cast `value` to the type expected by `canonical_property` and apply any
    pure (live-state-independent) clamp. Bools accept 0/1/true/false."""
    if canonical_property in _BOOL_PROPS:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    if canonical_property in _INT_PROPS:
        out = int(round(float(value)))
    else:
        out = float(value)

    if canonical_property in _CLAMPS:
        lo, hi = _CLAMPS[canonical_property]
        if out < lo:
            out = lo
        if out > hi:
            out = hi
    return out


def resolve_quantize_grid(name):
    """Map a friendly grid name ('1/8', '1/16t', ...) to its
    Live.Song.RecordingQuantization int. Raises ValueError listing options."""
    key = str(name).strip().lower()
    if key in QUANTIZE_GRID_MAP:
        return QUANTIZE_GRID_MAP[key]
    raise ValueError(
        "Unknown quantize grid '%s'. Available: %s"
        % (name, ", ".join(QUANTIZE_GRID_MAP.keys()))
    )
