"""Pure sample-sourcing helpers. No Live or socket dependency.

classify_sample / name_match / refine_kind_by_length are pure (no I/O).
icloud_placeholder_path touches the filesystem only (no Live).
"""

import os
import re

# Single-hit drum/percussion words that mark a one-shot when they appear as a
# whole word in the file name.
_ONE_SHOT_WORDS = (
    "kick", "snare", "hat", "hihat", "clap", "stab", "hit", "tom", "rim",
    "crash", "ride", "perc", "shaker", "cowbell", "fx", "vox",
)
# Folder/name tokens.
_ONE_SHOT_TOKENS = ("one shot", "one shots", "oneshot", "hits/", "hits ")
_LOOP_TOKENS = ("loop", "loops")
# A BPM in the name: "120 bpm", "90bpm", or a trailing "_128".
_BPM_RE = re.compile(r"\b\d{2,3}\s?bpm\b", re.IGNORECASE)
_TRAILING_NUM_RE = re.compile(r"_(\d{2,3})(?:\.\w+)?$")

_AUDIO_EXTS = (".wav", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg")


def _has_word(text, words):
    low = text.lower()
    for w in words:
        if re.search(r"\b%s\b" % re.escape(w), low):
            return True
    return False


def classify_sample(name, path):
    """Return "loop" | "one_shot" | "kit" | "instrument" from name + path.

    Priority (first match wins):
      1. .adg under a Drums/Kit folder            -> kit
      2. instrument preset (.adv)                 -> instrument
      3. one-shot tokens / single-hit drum words  -> one_shot
      4. loop tokens / a BPM in the name          -> loop
      5. fallback by extension (audio -> one_shot)
    """
    ext = os.path.splitext(name)[1].lower()
    low_path = path.lower().replace("\\", "/")
    low_name = name.lower()

    # 1. kit
    if ext == ".adg" and ("/drums/" in low_path or "/kit" in low_path
                          or low_path.startswith("drums/") or "kit" in low_path):
        return "kit"
    # 2. instrument
    if ext == ".adv":
        return "instrument"
    # 3. one_shot (but skip if a loop token is in the name itself)
    if (any(tok in low_path for tok in _ONE_SHOT_TOKENS) or _has_word(low_name, _ONE_SHOT_WORDS)) \
            and not any(tok in low_name for tok in _LOOP_TOKENS):
        return "one_shot"
    # 4. loop
    if (any(tok in low_path for tok in _LOOP_TOKENS)
            or _BPM_RE.search(low_name) or _TRAILING_NUM_RE.search(low_name)):
        return "loop"
    # 5. fallback: audio files default to one_shot (conservative -- refine after load)
    if ext in _AUDIO_EXTS:
        return "one_shot"
    return "one_shot"


def name_match(query, name, folder):
    """Return (matched, score) for a space-separated OR query against name+folder.

    matched is True if ANY query term appears in the name or folder
    (case-insensitive substring). score = term hits + a whole-word bonus per
    term that matches the name as a whole word (so exact-ish names rank above
    incidental substring hits). An empty query matches everything with score 0.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return True, 0
    low_name = name.lower()
    low_folder = folder.lower()
    score = 0
    matched = False
    for t in terms:
        in_name = t in low_name
        in_folder = t in low_folder
        if in_name or in_folder:
            matched = True
            score += 1
            if re.search(r"\b%s\b" % re.escape(t), low_name):
                score += 1
    return matched, score


def icloud_placeholder_path(sample_path):
    """Return the sibling '.<name>.icloud' stub path, or None.

    Returns None when the real file already exists (not a placeholder) or when
    no stub exists (not a known iCloud dataless file). Returns the stub path
    only when the real file is absent AND the stub is present -- i.e. a genuine
    undownloaded placeholder. Pure filesystem reads; no Live dependency.
    """
    if os.path.exists(sample_path):
        return None
    d = os.path.dirname(sample_path)
    base = os.path.basename(sample_path)
    stub = os.path.join(d, "." + base + ".icloud")
    return stub if os.path.exists(stub) else None


# A one-shot longer than this many beats is really a loop.
_LOOP_BEAT_THRESHOLD = 2.0


def refine_kind_by_length(kind, frames, sample_rate, tempo):
    """Upgrade a long 'one_shot' to 'loop' once true length is known.

    Only acts on kind == 'one_shot'. Returns kind unchanged for anything else,
    or when sample_rate/tempo are non-positive (can't compute beats).
    """
    if kind != "one_shot":
        return kind
    if not sample_rate or sample_rate <= 0 or not tempo or tempo <= 0:
        return kind
    duration_s = frames / float(sample_rate)
    beats = duration_s * tempo / 60.0
    return "loop" if beats > _LOOP_BEAT_THRESHOLD else kind
