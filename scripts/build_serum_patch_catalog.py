"""Scan factory .SerumPreset files and emit param_maps/serum2_patch.json.
Friendly param name = kParam* minus the 'kParam' prefix. Param ranges are the
observed min/max across all presets. mod_dest_params harvests the deterministic
(destModuleTypeString -> {destModuleParamName: destModuleParamID}) map. Mode enum
and mod_dest_types are spike constants. mod_sources starts empty (Task 7 oracle)."""
import glob, json, os, sys

from ableton_mcp_max import serum_state_codec as ssc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
MODULE_NODES = {
    "oscillator": ("Oscillator%d", 5),
    "filter": ("VoiceFilter%d", 2),
    "envelope": ("Env%d", 4),
    "lfo": ("LFO%d", 10),
}
MODES = {"wavetable": None, "multisample": "kOsc_MultiSample", "sample": "kOsc_Sample",
         "granular": "kOsc_Granular", "spectral": "kOsc_Spectral"}
MOD_DEST_TYPES = {"oscillator": "Oscillator", "filter": "VoiceFilter", "envelope": "Env",
                  "lfo": "LFO", "wt": "WTOsc", "macro": "Macro", "global": "Global"}


def friendly(kparam):
    return kparam[6:] if kparam.startswith("kParam") else kparam


def _pp(node):
    x = node.get("plainParams") if isinstance(node, dict) else None
    return x if isinstance(x, dict) else {}


def scan(root):
    ranges = {m: {} for m in MODULE_NODES}     # module -> kparam -> [min,max]
    dest = {}                                   # typeString -> {paramName: paramID}
    files = glob.glob(os.path.join(root, "**", "*.SerumPreset"), recursive=True)
    for p in files:
        try:
            tree = ssc.decode(open(p, "rb").read()).tree
        except Exception:
            continue
        for m, (fmt, count) in MODULE_NODES.items():
            for n in range(count):
                for k, v in _pp(tree.get(fmt % n)).items():
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        continue
                    cur = ranges[m].setdefault(k, [float(v), float(v)])
                    cur[0] = min(cur[0], float(v)); cur[1] = max(cur[1], float(v))
        for n in range(64):
            ms = tree.get("ModSlot%d" % n)
            if not isinstance(ms, dict) or "destModuleTypeString" not in ms:
                continue
            ts = ms.get("destModuleTypeString"); pn = ms.get("destModuleParamName")
            pid = ms.get("destModuleParamID")
            if ts is None or pn is None or pid is None:
                continue
            dest.setdefault(ts, {}).setdefault(pn, int(pid))
    return ranges, dest, len(files)


def build(root):
    ranges, dest, nfiles = scan(root)
    modules = {}
    for m, (fmt, count) in MODULE_NODES.items():
        params = {friendly(k): {"kparam": k, "native_min": lo, "native_max": hi}
                  for k, (lo, hi) in sorted(ranges[m].items())}
        entry = {"count": count, "node": fmt.replace("%d", "{n}"), "params": params}
        if m == "oscillator":
            entry["modes"] = MODES
        modules[m] = entry
    modules["macro"] = {"count": 8, "node": "Macro{n}"}
    return {"plugin": "Serum2", "scanned_presets": nfiles, "modules": modules,
            "mod_dest_types": MOD_DEST_TYPES,
            "mod_dest_params": {ts: dict(sorted(d.items())) for ts, d in sorted(dest.items())},
            "mod_sources": {}}


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else FACTORY
    out = os.path.join(os.path.dirname(__file__), "..", "ableton_mcp_max",
                       "param_maps", "serum2_patch.json")
    cat = build(root)
    with open(out, "w") as fh:
        json.dump(cat, fh, indent=1, sort_keys=True)
    print("wrote %s (%d presets, dest_types=%d)"
          % (out, cat["scanned_presets"], len(cat["mod_dest_params"])))
