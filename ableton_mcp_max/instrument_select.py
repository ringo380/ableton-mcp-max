"""Instrument-selection intelligence: choose which engine to reach for.

Pure module imported by server.py only. Loads a curated capability matrix
(param_maps/instrument_profiles.json), parses a free-text intent, and scores
each engine. Live signals (Serum installed, instance count, portability) are
resolved in server.py and passed in as an environment dict.
"""
import json
import os
import re

_PROFILES_PATH = os.path.join(os.path.dirname(__file__), "param_maps",
                              "instrument_profiles.json")


def load_profiles(path=None):
    """Load the capability matrix. Raises FileNotFoundError if missing."""
    with open(path or _PROFILES_PATH, "r") as fh:
        return json.load(fh)


def _phrase_present(text, phrase):
    """Word-boundary match so 'arp' does not match 'harp'."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def _first_match(text, vocab):
    for category, phrases in vocab.items():
        if any(_phrase_present(text, ph) for ph in phrases):
            return category
    return None


def _all_matches(text, vocab):
    return [category for category, phrases in vocab.items()
            if any(_phrase_present(text, ph) for ph in phrases)]


def parse_intent(text, profiles):
    t = (text or "").lower()
    return {"role": _first_match(t, profiles["role_vocab"]),
            "genre": _first_match(t, profiles["genre_vocab"]),
            "character": _all_matches(t, profiles["character_vocab"])}


_SERUM_INSTALL_CANDIDATES = [
    "/Library/Audio/Plug-Ins/VST3/Serum2.vst3",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3/Serum2.vst3"),
    "/Library/Audio/Plug-Ins/VST3/Serum.vst3",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3/Serum.vst3"),
    "/Library/Audio/Plug-Ins/Components/Serum2.component",
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components/Serum2.component"),
    "/Library/Audio/Plug-Ins/Components/Serum.component",
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components/Serum.component"),
    "/Library/Audio/Presets/Xfer Records/Serum 2 Presets",
]

_PLUGIN_CLASSES = ("PluginDevice", "AuPluginDevice")


def serum_installed(candidates=None):
    for p in (candidates if candidates is not None else _SERUM_INSTALL_CANDIDATES):
        if os.path.exists(p):
            return True
    return False


def classify_device(name, class_name):
    if class_name in _PLUGIN_CLASSES:
        if name and "serum" in name.lower():
            return "serum"
        return "plugin"
    return "native"


def summarize_environment(tracks_devices, serum_is_installed, prefer_native_arg):
    serum_instances = 0
    third_party = False
    total = 0
    for devs in tracks_devices:
        for d in devs:
            total += 1
            kind = classify_device(d.get("name"), d.get("class_name"))
            if kind == "serum":
                serum_instances += 1
                third_party = True
            elif kind == "plugin":
                third_party = True
    if prefer_native_arg is None:
        prefer_native = bool(total > 0 and not third_party)
    else:
        prefer_native = bool(prefer_native_arg)
    return {"serum_installed": bool(serum_is_installed),
            "serum_instances": serum_instances,
            "prefer_native": prefer_native}
