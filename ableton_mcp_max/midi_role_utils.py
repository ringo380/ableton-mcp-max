"""MIDI-aware instrument selection: what a part IS, from its notes.

Pure module imported by server.py. Reads a note list (the dicts get_clip_notes
returns: pitch, start_time, duration, velocity), measures it, classifies the
musical texture, resolves a catalog role with the track/file name as a prior,
and scores catalog rows and installed plugins against that role. Nothing here
touches Live.
"""
import json
import math
import os
import re
from collections import Counter

_MAP_PATH = os.path.join(os.path.dirname(__file__), "param_maps",
                         "midi_role_map.json")

GM_DRUM_LOW, GM_DRUM_HIGH = 35, 81


def load_role_map(path=None):
    with open(path or _MAP_PATH, "r") as fh:
        return json.load(fh)


# --- features --------------------------------------------------------------

def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def _max_polyphony(notes):
    events = []
    for n in notes:
        s = float(n["start_time"])
        events.append((s, 1))
        events.append((s + max(1e-6, float(n.get("duration", 0))), -1))
    events.sort(key=lambda e: (e[0], e[1]))  # ends before starts at equal time
    cur = best = 0
    for _t, d in events:
        cur += d
        best = max(best, cur)
    return best


def _coverage(notes, span):
    """Fraction of the span during which at least one note sounds."""
    if span <= 0:
        return 0.0
    ivs = sorted((float(n["start_time"]),
                  float(n["start_time"]) + max(1e-6, float(n.get("duration", 0))))
                 for n in notes)
    covered = 0.0
    cs, ce = ivs[0]
    for s, e in ivs[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            covered += ce - cs
            cs, ce = s, e
    covered += ce - cs
    return min(1.0, covered / span)


def note_features(notes):
    """Measure a note list. All times in beats (clip units)."""
    notes = [n for n in (notes or []) if not n.get("mute")]
    if not notes:
        return {"count": 0}
    pitches = [int(n["pitch"]) for n in notes]
    starts = [float(n["start_time"]) for n in notes]
    durs = [max(0.0, float(n.get("duration", 0))) for n in notes]
    vels = [float(n.get("velocity", 100)) for n in notes]
    first = min(starts)
    last_end = max(s + d for s, d in zip(starts, durs))
    span = max(1e-6, last_end - first)
    # onsets: notes that start together (within a 32nd) form one onset group
    groups = Counter(round(s * 8) for s in starts)
    sizes = list(groups.values())
    chord_onsets = sum(1 for z in sizes if z >= 3)
    dyad_onsets = sum(1 for z in sizes if z == 2)
    pc = Counter(pitches)
    top3 = sum(c for _p, c in pc.most_common(3)) / float(len(pitches))
    # melodic step between successive onset groups (top note of each group)
    tops = {}
    for p, s in zip(pitches, starts):
        k = round(s * 8)
        tops[k] = max(tops.get(k, -1), p)
    seq = [tops[k] for k in sorted(tops)]
    steps = [abs(b - a) for a, b in zip(seq, seq[1:])]
    mean_vel = sum(vels) / len(vels)
    vel_std = math.sqrt(sum((v - mean_vel) ** 2 for v in vels) / len(vels))
    in_drum_range = sum(1 for p in pitches if GM_DRUM_LOW <= p <= GM_DRUM_HIGH)
    return {
        "count": len(notes),
        "span_beats": round(span, 3),
        "pitch_low": min(pitches),
        "pitch_high": max(pitches),
        "pitch_median": _median(pitches),
        "distinct_pitches": len(pc),
        "top3_pitch_share": round(top3, 3),
        "max_polyphony": _max_polyphony(notes),
        "onsets": len(sizes),
        "chord_onset_ratio": round(chord_onsets / float(len(sizes)), 3),
        "dyad_onset_ratio": round(dyad_onsets / float(len(sizes)), 3),
        "onsets_per_beat": round(len(sizes) / span, 3),
        "notes_per_beat": round(len(notes) / span, 3),
        "median_duration": round(_median(durs), 3),
        "long_note_ratio": round(sum(1 for d in durs if d >= 2.0) / float(len(durs)), 3),
        "short_note_ratio": round(sum(1 for d in durs if d <= 0.25) / float(len(durs)), 3),
        "coverage": round(_coverage(notes, span), 3),
        "mean_step": round(sum(steps) / len(steps), 2) if steps else 0.0,
        "velocity_mean": round(mean_vel, 1),
        "velocity_std": round(vel_std, 1),
        "drum_range_share": round(in_drum_range / float(len(pitches)), 3),
        "pitch_class_histogram": _pc_hist(pitches, durs),
    }


def _pc_hist(pitches, durs):
    h = [0.0] * 12
    for p, d in zip(pitches, durs):
        h[p % 12] += max(0.05, d)
    tot = sum(h) or 1.0
    return [round(x / tot, 4) for x in h]


# --- key guess (Krumhansl-Schmuckler) ---------------------------------------

_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _corr(a, b):
    ma, mb = sum(a) / 12.0, sum(b) / 12.0
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def guess_key(hist):
    """Best (key, mode, correlation) for a 12-bin pitch-class histogram."""
    if not hist or sum(hist) <= 0:
        return None
    best = None
    for i in range(12):
        rot = hist[i:] + hist[:i]
        for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
            c = _corr(rot, prof)
            if best is None or c > best[2]:
                best = (_NAMES[i], mode, c)
    return {"key": "%s %s" % (best[0], best[1]), "correlation": round(best[2], 3)}


def merge_histograms(hists):
    out = [0.0] * 12
    for h in hists:
        for i, v in enumerate(h or []):
            out[i] += v
    tot = sum(out) or 1.0
    return [v / tot for v in out]


# --- texture + role -----------------------------------------------------------

TEXTURES = ("drums", "bass", "pad", "keys", "stabs", "lead", "sustained_line",
            "arp", "fx", "sparse")


def classify_texture(f):
    """Content-only classification. Returns (texture, confidence, evidence)."""
    if not f or f.get("count", 0) == 0:
        return "sparse", 0.0, ["no notes"]
    ev = []
    n = f["count"]
    if n < 8 or f["notes_per_beat"] < 0.05:
        ev.append("%d notes over %.0f beats" % (n, f["span_beats"]))
        return "sparse", 0.6, ev
    # Drum hits: GM drum range, hits (not held notes), a few pitches carry
    # most of the part. A 16th-note melodic run has longer notes and spreads
    # across more pitches.
    # Hits are near-zero length, or land together (kick + hat); an arp does
    # neither.
    hits = (f["median_duration"] <= 0.1
            or f["dyad_onset_ratio"] + f["chord_onset_ratio"] >= 0.3)
    drumlike = (f["drum_range_share"] >= 0.9 and f["median_duration"] <= 0.2
                and f["distinct_pitches"] <= 24 and f["top3_pitch_share"] >= 0.6
                and hits)
    if drumlike:
        ev.append("pitches %d-%d sit in the GM drum range, hits not held notes, 3 pitches carry %.0f%%"
                  % (f["pitch_low"], f["pitch_high"], f["top3_pitch_share"] * 100))
        return "drums", 0.8, ev
    # Dyads alone (octave doublings, harmony lines) do not make a part chordal.
    poly = (f["chord_onset_ratio"] >= 0.25
            or (f["max_polyphony"] >= 4
                and f["dyad_onset_ratio"] + f["chord_onset_ratio"] >= 0.5))
    if f["pitch_median"] <= 50 and f["chord_onset_ratio"] < 0.15:
        ev.append("median pitch %d (below C3), no chords" % f["pitch_median"])
        return "bass", 0.85, ev
    if poly:
        ev.append("%.0f%% of onsets are chords, up to %d notes at once"
                  % (f["chord_onset_ratio"] * 100, f["max_polyphony"]))
        if f["median_duration"] >= 1.5 or (f["long_note_ratio"] >= 0.4 and f["onsets_per_beat"] < 0.5):
            ev.append("sustained (median %.2f beats)" % f["median_duration"])
            return "pad", 0.8, ev
        if f["median_duration"] <= 0.5 and f["onsets_per_beat"] >= 0.5:
            ev.append("short rhythmic chords (median %.2f beats)" % f["median_duration"])
            return "stabs", 0.7, ev
        ev.append("comped chords (median %.2f beats)" % f["median_duration"])
        return "keys", 0.75, ev
    # monophonic-ish
    if f["onsets_per_beat"] >= 2.0 and f["median_duration"] <= 0.35:
        ev.append("%.1f onsets per beat, short notes" % f["onsets_per_beat"])
        return "arp", 0.7, ev
    if f["median_duration"] >= 1.0 or f["coverage"] >= 0.7 and f["onsets_per_beat"] < 1.0:
        ev.append("single sustained line (median %.2f beats, %.0f%% of time sounding)"
                  % (f["median_duration"], f["coverage"] * 100))
        return "sustained_line", 0.7, ev
    ev.append("single melodic line, median pitch %d, mean step %.1f semitones"
              % (f["pitch_median"], f["mean_step"]))
    return "lead", 0.7, ev


# specific instruments before generic words: "Lead Vocals" is a vocal
_HINT_ORDER = ("vocal", "drums", "percussion", "bass", "strings", "brass",
               "winds", "keys", "mallets", "pluck", "arp", "pad", "fx", "lead")


def name_role(name, role_map):
    """Role implied by a track/file name, or None."""
    t = (name or "").lower()
    toks = set(re.split(r"[\W_]+", t))
    hints = role_map["name_hints"]
    order = list(_HINT_ORDER) + [r for r in hints if r not in _HINT_ORDER]
    for role in order:
        for w in hints.get(role, []):
            if w in toks or (len(w) > 3 and w in t):
                return role
    return None


# texture -> default role, and which name roles may refine it
_TEXTURE_DEFAULT = {
    "drums": "drums", "bass": "bass", "pad": "pad", "keys": "keys",
    "stabs": "stabs", "lead": "lead", "sustained_line": "lead", "arp": "arp",
    "fx": "fx", "sparse": "fx",
}
_REFINE = {
    "pad": {"strings", "vocal", "brass", "keys", "pad", "winds"},
    "keys": {"keys", "strings", "brass", "pluck", "mallets", "vocal", "pad"},
    "stabs": {"brass", "keys", "pluck", "stabs", "strings", "mallets"},
    "lead": {"lead", "vocal", "winds", "brass", "strings", "pluck", "keys", "mallets"},
    "sustained_line": {"vocal", "winds", "brass", "strings", "lead", "pad"},
    # a fast run is still a flute / voice / guitar if the name says so
    "arp": {"arp", "pluck", "keys", "mallets", "lead", "vocal", "winds", "brass",
            "strings"},
    "sparse": {"fx", "percussion", "drums", "vocal", "brass", "strings", "winds",
               "lead", "keys", "pad"},
    "drums": {"drums", "percussion"},
    "bass": {"bass"},
}


SMALL_PART = 50  # below this many notes the content read is weak evidence


def resolve_role(texture, hint, count=None):
    """Combine content texture with the name hint. Content wins on a conflict;
    the hint refines within the family the texture allows. A small part (a
    few fills or hits) is too little evidence to overrule its name."""
    default = _TEXTURE_DEFAULT[texture]
    if hint is None:
        return default, None
    if hint in _REFINE.get(texture, set()):
        return hint, None
    if count is not None and count < SMALL_PART:
        return hint, None
    return default, ("name says %s but the notes read as %s" % (hint, texture))


def describe_part(notes, name=None, role_map=None):
    role_map = role_map or load_role_map()
    f = note_features(notes)
    texture, conf, ev = classify_texture(f)
    hint = name_role(name, role_map)
    role, conflict = resolve_role(texture, hint, f.get("count"))
    if conflict:
        conf = round(conf * 0.7, 2)
    return {"features": f, "texture": texture, "confidence": conf,
            "evidence": ev, "name_hint": hint, "role": role,
            "conflict": conflict,
            "key_guess": guess_key(f.get("pitch_class_histogram"))}


# --- candidate scoring -----------------------------------------------------

_FOLDER_PRIMARY = 10.0
_FOLDER_SECONDARY = 5.0
_TERM_HIT = 1.5
_INTENT_HIT = 2.0
_FEATURE_HIT = 2.0
_FEATURE_AVOID = 2.5
_USED_PENALTY = 6.0  # more than primary-minus-secondary folder gap
_CURRENT_BONUS = 0.5  # a fitting sound already on the track wins a tie


def _rule_applies(when, f):
    """when: {<feature>_min: x, <feature>_max: y, ...}. pitch_range is derived."""
    if not f:
        return False
    vals = dict(f)
    if "pitch_low" in f and "pitch_high" in f:
        vals["pitch_range"] = f["pitch_high"] - f["pitch_low"]
    for key, bound in when.items():
        if key.endswith("_min"):
            v = vals.get(key[:-4])
            if v is None or v < bound:
                return False
        elif key.endswith("_max"):
            v = vals.get(key[:-4])
            if v is None or v > bound:
                return False
    return True


def active_feature_terms(role, role_map, features):
    """The boost/avoid term rules that fire for this part's measurements."""
    out = []
    for rule in (role_map["roles"].get(role) or {}).get("feature_terms", []):
        if _rule_applies(rule.get("when", {}), features):
            out.append(rule)
    return out


def _terms(text):
    return [t for t in re.split(r"[\W_]+", (text or "").lower()) if t]


def _engine_of(folder):
    return (folder or "").split("/", 1)[0]


def _category_of(folder):
    parts = (folder or "").split("/", 1)
    return parts[1] if len(parts) > 1 else ""


def role_folders(role, role_map):
    r = role_map["roles"].get(role) or {}
    return list(r.get("folders", [])), list(r.get("secondary_folders", []))


def score_candidates(rows, role, role_map, intent="", used_names=(),
                     limit=5, features=None, current_names=()):
    """Rank device-preset catalog rows for a role. rows: dicts with name, uri,
    folder, tags. Returns the top `limit` with a score and a why string, one
    entry per preset name (the same patch is filed under its engine AND under
    Instrument Rack; the engine copy wins the tie). features (from
    note_features) switch on the role's feature_terms rules; current_names
    (the track's devices) win ties so a fitting sound is not churned."""
    r = role_map["roles"].get(role) or {}
    primary, secondary = role_folders(role, role_map)
    terms = [t.lower() for t in r.get("terms", [])]
    intent_terms = [t for t in _terms(intent) if len(t) > 2]
    rules = active_feature_terms(role, role_map, features)
    boost = [(t.lower(), rule.get("why", "")) for rule in rules for t in rule.get("boost", [])]
    avoid = [(t.lower(), rule.get("why", "")) for rule in rules for t in rule.get("avoid", [])]
    pref = dict(role_map["engine_preference"].get("default", {}))
    pref.update(role_map["engine_preference"].get(role, {}))
    used = {u.lower() for u in used_names if u}
    current = {c.lower() for c in current_names if c}
    scored = []
    for row in rows:
        folder = row.get("folder") or ""
        cat = _category_of(folder)
        why = []
        s = 0.0
        if cat in primary:
            s += _FOLDER_PRIMARY
            why.append("%s preset" % cat)
        elif cat in secondary:
            s += _FOLDER_SECONDARY
            why.append("%s (related)" % cat)
        else:
            continue
        hay = " ".join([row.get("name") or "", folder, row.get("tags") or ""]).lower()
        hits = [t for t in terms if t in hay]
        if hits:
            s += _TERM_HIT * len(hits)
            why.append("matches " + "/".join(hits))
        name_words = set(_terms(row.get("name")))
        ihits = [t for t in intent_terms if t in hay]
        if ihits:
            # a hit in the preset's own name outranks one in its folder/tags
            s += _INTENT_HIT * len(ihits) + sum(1.0 for t in ihits if t in name_words)
            why.append("intent " + "/".join(ihits))
        bh = [(t, w) for t, w in boost if t in name_words]
        if bh:
            s += _FEATURE_HIT * len(bh)
            why.append("%s (%s)" % ("/".join(t for t, _w in bh), bh[0][1]))
        ah = [(t, w) for t, w in avoid if t in name_words]
        if ah:
            s -= _FEATURE_AVOID * len(ah)
            why.append("but %s (%s)" % ("/".join(t for t, _w in ah), ah[0][1]))
        eng = _engine_of(folder)
        s += pref.get(eng, 0.0)
        name_l = (row.get("name") or "").lower()
        if name_l in current:
            s += _CURRENT_BONUS
            why.append("current instrument")
        elif name_l in used:
            s -= _USED_PENALTY
            why.append("already used in this set")
        scored.append((s, eng == "Instrument Rack", row, why))
    scored.sort(key=lambda x: (-x[0], x[1], x[2].get("name") or ""))
    out, seen = [], set()
    for s, _rack, row, why in scored:
        key = (row.get("name") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": row.get("name"), "uri": row.get("uri"),
                    "folder": row.get("folder"), "score": round(s, 2),
                    "why": "; ".join(why)})
        if len(out) >= limit:
            break
    return out


def score_kits(items, intent="", used_names=(), limit=5, current_names=()):
    """Rank Drum Rack kits (browser items under 'drums') by intent terms. The
    kit already on the track wins a tie."""
    intent_terms = [t for t in _terms(intent) if len(t) > 2]
    used = {u.lower() for u in used_names if u}
    current = {c.lower() for c in current_names if c}
    out = []
    for it in items:
        if it.get("is_folder") or it.get("is_device") or not it.get("is_loadable"):
            continue
        name = re.sub(r"\.adg$", "", it.get("name") or "", flags=re.I)
        s = 1.0
        why = ["drum kit"]
        hits = [t for t in intent_terms if t in name.lower()]
        if hits:
            s += _INTENT_HIT * len(hits)
            why.append("intent " + "/".join(hits))
        if name.lower() in current:
            s += _CURRENT_BONUS
            why.append("current instrument")
        elif name.lower() in used:
            s -= _USED_PENALTY
            why.append("already used in this set")
        out.append({"name": name, "uri": it.get("uri"), "folder": "Drums",
                    "score": round(s, 2), "why": "; ".join(why)})
    out.sort(key=lambda c: (-c["score"], c["name"]))
    return out[:limit]


def plugin_candidates(role, role_map, installed):
    """Plugin suggestions for a role, limited to plugins Live's browser lists.
    installed: {name: uri}. A plugin loads bare: the patch is a manual step."""
    out = []
    for p in (role_map["roles"].get(role) or {}).get("plugins", []):
        uri = installed.get(p["name"])
        if not uri:
            continue
        out.append({"name": p["name"], "uri": uri, "kind": "plugin",
                    "patch_selection": "manual", "why": p.get("why", "")})
    return out


def name_terms(name):
    """Words of a track name worth matching against preset names ('Guitar
    MIDI' -> ['guitar']); generic words are dropped."""
    drop = {"midi", "track", "audio", "part", "stem", "new", "the", "and",
            "ch", "melodic"}
    return [t for t in _terms(name) if len(t) > 2 and t not in drop
            and not t.isdigit()]


def intent_for(desc, context=None):
    """A short free-text intent the free-text tools can also consume."""
    context = context or {}
    bits = [desc["role"]]
    if desc["texture"] not in (desc["role"], "sparse"):
        bits.append(desc["texture"].replace("_", " "))
    if context.get("genre"):
        bits.append(context["genre"])
    if context.get("tempo"):
        bits.append("%d bpm" % round(context["tempo"]))
    if desc.get("key_guess"):
        bits.append(desc["key_guess"]["key"])
    return " ".join(bits)
