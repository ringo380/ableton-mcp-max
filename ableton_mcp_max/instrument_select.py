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
