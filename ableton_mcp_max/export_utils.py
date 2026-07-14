"""Pure resolver for render_audio: validate export options and turn them into a
plan keyed to the Export dialog's real AX description strings.

No I/O. The AX strings here were read off Live 12.4.2's Export Audio/Video
dialog (see the design spec) - do not invent new ones.
"""

FILE_TYPES = ("WAV", "AIFF", "FLAC", "MP3")
BIT_DEPTHS = ("16", "24", "32")
SAMPLE_RATES = ("44100", "48000", "88200", "96000", "176400", "192000")
DITHER_OPTIONS = ("No Dither", "Triangular", "Rectangular",
                  "POW-r 1", "POW-r 2", "POW-r 3")


def _one_of(value, allowed, label):
    v = str(value).strip()
    if v not in allowed:
        raise ValueError("%s must be one of %s (got %r)."
                         % (label, ", ".join(allowed), value))
    return v


def clean_render_name(name):
    """Basename for the render. Rejects the characters that hijack the macOS
    save panel: '/' opens Go-to-Folder, ':' is the legacy path separator."""
    n = (name or "").strip()
    if not n:
        raise ValueError("name is required (the render needs a file name).")
    for ch in ("/", ":"):
        if ch in n:
            raise ValueError("name may not contain %r." % ch)
    return n


def loop_range_for(start_bar, end_bar, song_length, sig_num):
    """(start_beats, length_beats) for the arrangement loop that will seed the
    export range. Bars are 1-based as Live displays them, so bar N begins at
    (N-1)*sig_num beats. Both bars None => the whole song."""
    if start_bar is None and end_bar is None:
        length = float(song_length)
        if length <= 0:
            raise ValueError("The song is empty (song_length is 0) - "
                             "nothing to render.")
        return (0.0, length)
    if start_bar is None or end_bar is None:
        raise ValueError("Pass BOTH start_bar and end_bar, or neither "
                         "(neither = render the whole song).")
    if int(start_bar) < 1:
        raise ValueError("start_bar is 1-based (got %r)." % start_bar)
    if int(end_bar) <= int(start_bar):
        raise ValueError("end_bar (%r) must be greater than start_bar (%r)."
                         % (end_bar, start_bar))
    beats = float(sig_num)
    start = (int(start_bar) - 1) * beats
    length = (int(end_bar) - int(start_bar)) * beats
    return (start, length)


def plan_export(file_type="WAV", bit_depth=24, sample_rate=44100,
                normalize=False, mp3=False, mono=False, include_returns=True,
                analysis_file=True, dither="No Dither"):
    """Validated plan for the Export dialog: which popups to set and what every
    managed toggle's value must END UP as. The executor reads each toggle and
    clicks only on a mismatch (clicking TOGGLES - a blind click inverts a
    control that is already correct)."""
    ft = _one_of(file_type, FILE_TYPES, "file_type")
    depth = _one_of(bit_depth, BIT_DEPTHS, "bit_depth")
    rate = _one_of(sample_rate, SAMPLE_RATES, "sample_rate")
    dith = _one_of(dither, DITHER_OPTIONS, "dither")

    # Live emits one file per enabled encoder: file_type MP3 means MP3 only;
    # mp3=True alongside a PCM type emits BOTH (observed live).
    pcm_on = ft != "MP3"
    mp3_on = bool(mp3) or ft == "MP3"

    popups = [
        {"description": "Rendered Track Chooser", "value": "Main"},
        {"description": "Sample Rate", "value": rate},
    ]
    if pcm_on:
        popups.append({"description": "File Type", "value": ft})
        popups.append({"description": "Recording Bit Depth", "value": depth})
        popups.append({"description": "Dither Options", "value": dith})

    def flag(b):
        return "On" if b else "Off"

    toggles = [
        {"description": "Include Return and Main Effects",
         "want": flag(include_returns)},
        {"description": "Render as Loop", "want": "Off"},
        {"description": "Convert to Mono", "want": flag(mono)},
        {"description": "Normalize", "want": flag(normalize)},
        {"description": "Create Analysis File", "want": flag(analysis_file)},
        {"description": "Encode PCM", "want": flag(pcm_on)},
        {"description": "Encode MP3", "want": flag(mp3_on)},
    ]
    return {"popups": popups, "toggles": toggles,
            "file_type": ft, "bit_depth": depth, "sample_rate": rate,
            "pcm": pcm_on, "mp3": mp3_on}
