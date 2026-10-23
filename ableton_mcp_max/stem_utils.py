"""Pure helpers for stem separation (Demucs CLI) -> Arrangement layout.

Import-light by contract: stdlib only. No librosa, no torch, no Ableton.
Imported by server.py only (the Remote Script runs in Live's own Python).
"""

import json
import os
import re

# Layout order is also the demucs output-filename set for each model.
MODELS = {
    "htdemucs": {
        "demucs_model": "htdemucs",
        "two_stems": None,
        "stems": ["drums", "bass", "other", "vocals"],
    },
    "htdemucs_6s": {
        "demucs_model": "htdemucs_6s",
        "two_stems": None,
        "stems": ["drums", "bass", "other", "vocals", "guitar", "piano"],
    },
    "two_stems": {
        "demucs_model": "htdemucs",
        "two_stems": "vocals",
        "stems": ["vocals", "no_vocals"],
    },
}

_ALIASES = {
    "htdemucs": "htdemucs",
    "4": "htdemucs",
    "4stem": "htdemucs",
    "htdemucs_6s": "htdemucs_6s",
    "6": "htdemucs_6s",
    "6stem": "htdemucs_6s",
    "6s": "htdemucs_6s",
    "two_stems": "two_stems",
    "2": "two_stems",
    "2stem": "two_stems",
    "vocals": "two_stems",
}


def validate_model(model):
    """Return a copy of the model spec for `model` (case/alias-insensitive)."""
    key = _ALIASES.get(str(model).strip().lower())
    if key is None:
        raise ValueError(
            "Unknown model %r. Choose one of: htdemucs (4-stem), "
            "htdemucs_6s (6-stem), two_stems." % (model,))
    spec = MODELS[key]
    return {
        "demucs_model": spec["demucs_model"],
        "two_stems": spec["two_stems"],
        "stems": list(spec["stems"]),
    }


def build_demucs_cmd(audio_path, model, out_dir, device):
    """Build the demucs CLI argv. Demucs writes <out_dir>/<model>/<name>/*.wav."""
    spec = validate_model(model)
    cmd = ["demucs", "-n", spec["demucs_model"], "-o", out_dir, "-d", device]
    if spec["two_stems"]:
        cmd.append("--two-stems=%s" % spec["two_stems"])
    cmd.append(audio_path)
    return cmd


def expected_stem_paths(out_dir, model, track_basename):
    """[(stem_name, abs_wav_path)] in layout order, as demucs writes them."""
    spec = validate_model(model)
    base = "%s/%s/%s" % (out_dir, spec["demucs_model"], track_basename)
    return [(name, "%s/%s.wav" % (base, name)) for name in spec["stems"]]


def key_to_scale_args(pitch_class, mode):
    """Map a detected pitch class + mode to (key, scale) for set_song_scale."""
    scale = "minor" if str(mode).strip().lower() == "minor" else "major"
    return (str(pitch_class).strip(), scale)


def parse_analysis(json_str):
    """Parse analyze_audio.py output into (tempo, key, scale).

    Tolerant: any parse error or missing field yields None for that value.
    """
    try:
        data = json.loads(json_str)
    except (ValueError, TypeError):
        return (None, None, None)
    if not isinstance(data, dict):
        return (None, None, None)
    tempo = data.get("tempo")
    tempo = float(tempo) if isinstance(tempo, (int, float)) else None
    pc = data.get("key_pitch_class")
    mode = data.get("mode")
    if pc and mode:
        key, scale = key_to_scale_args(pc, mode)
    else:
        key, scale = (None, None)
    return (tempo, key, scale)


def resolve_device(device, machine):
    """auto -> mps on Apple Silicon (arm64), else cpu. Explicit values pass through."""
    if device != "auto":
        return device
    return "mps" if str(machine).lower() in ("arm64", "aarch64") else "cpu"


# Only formats _read_audio_meta can measure: an unknown length would skip the
# start/end normalize and could leave a stem truncated or offset.
STEM_EXTS = (".wav", ".aif", ".aiff")
_NUMBERED = re.compile(r"^(\d+)[\s._-]+(.+)$")
_BRACKETED = re.compile(r"^.+\(([^()]+)\)$")


def order_stem_files(names):
    """Audio file names from a stem pack, in pack order: a leading number
    ('0 Lead Vocals.wav', '10 Woodwinds.wav') sorts numerically, the rest
    after it by name."""
    def key(n):
        m = _NUMBERED.match(os.path.splitext(n)[0])
        return (0, int(m.group(1)), n.lower()) if m else (1, 0, n.lower())
    return sorted((n for n in names if n.lower().endswith(STEM_EXTS)), key=key)


def stem_track_name(file_name):
    """Track name for a stem file: the name without extension or a leading
    pack number ('2 Bass.wav' -> 'Bass'), or the part in brackets when the
    pack names files 'Song (Part)' ('Waiting for Nothing (Bass).wav' -> 'Bass')."""
    base = os.path.splitext(os.path.basename(file_name))[0]
    m = _NUMBERED.match(base)
    if m:
        return m.group(2).strip()
    m = _BRACKETED.match(base)
    return m.group(1).strip() if m else base
