"""Master-track Ozone preparation logic (pure, imported by server.py only).

Given the master's device list, decide which older Ozone versions to disable,
whether an Ozone 12 can be reused, and whether a fresh Ozone 12 must be loaded.
Detection is EXACT-name (after strip) so the single-module component plugins
(e.g. 'Ozone 12 Maximizer') are never mistaken for the full suite. PROPOSE
ONLY - the executor in server.py performs the device I/O.
"""

OZONE_SUITE_NAMES = frozenset(["Ozone 9", "Ozone 10", "Ozone 11", "Ozone 12"])
OZONE_12 = "Ozone 12"
OZONE_12_URI = "query:Plugins#VST3:iZotope:Ozone%2012"


def _name(device):
    return (device.get("name") or "").strip()


def plan_master_ozone(devices):
    """Return the action plan for the master's device list.

    devices: ordered list of {"index": int, "name": str, "is_on": bool}.
    Returns {"target_index", "action", "disable_indices", "load_required"}.
    """
    disable_indices = [d["index"] for d in devices
                       if _name(d) in OZONE_SUITE_NAMES and _name(d) != OZONE_12]
    twelves = [d for d in devices if _name(d) == OZONE_12]
    if twelves:
        target = min(twelves, key=lambda d: d["index"])
        action = "reused" if target.get("is_on") else "reused_reenabled"
        return {"target_index": target["index"], "action": action,
                "disable_indices": disable_indices, "load_required": False}
    return {"target_index": None, "action": "loaded",
            "disable_indices": disable_indices, "load_required": True}


def pick_loaded_target(before, after):
    """Index of the Ozone 12 that appeared after a load.

    Prefers an index present in `after` but not `before`; falls back to the
    lowest Ozone 12 index present; None if none exist.
    """
    before_12 = {d["index"] for d in before if _name(d) == OZONE_12}
    after_12 = sorted(d["index"] for d in after if _name(d) == OZONE_12)
    new = [i for i in after_12 if i not in before_12]
    if new:
        return new[0]
    return after_12[0] if after_12 else None
