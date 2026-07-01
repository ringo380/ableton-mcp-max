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
