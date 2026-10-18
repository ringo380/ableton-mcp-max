"""Pure analysis helpers for the track-analysis feature. No Live dependencies.

Server-side only (the Remote Script in Live's embedded Python cannot import
this). Provides a dotted-path resolver, a declarative predicate evaluator, and
the rule -> findings engine. Rules are DATA (see ableton_mcp_max/rulesets/*.json);
this module is the fixed engine that runs them.
"""

import math
import re  # used by the predicate evaluator / evidence templating added in later slices


def resolve_path(obj, path):
    """Resolve a dotted path against a nested dict/list snapshot.

    Segments ending in ``[*]`` project over a list and map the remaining path
    over each element, flattening one level. A missing key yields ``None`` for a
    scalar walk, or is skipped within a projection. Returns a scalar, or a list
    when any ``[*]`` wildcard is traversed.
    """
    return _walk(obj, path.split("."))


def _walk(obj, parts):
    if not parts:
        return obj
    part, rest = parts[0], parts[1:]
    wildcard = part.endswith("[*]")
    key = part[:-3] if wildcard else part
    nxt = obj.get(key) if isinstance(obj, dict) else None  # dict-key walk only; integer indexing into lists is not supported (yields None)
    if wildcard:
        if not isinstance(nxt, list):
            return []
        out = []
        for item in nxt:
            val = _walk(item, rest)
            # flatten one level: a wildcard child that itself projected yields a list
            out.extend(val) if isinstance(val, list) else out.append(val)
        return out
    return _walk(nxt, rest)


VALID_OPS = frozenset({
    "equals", "gt", "lt", "gte", "lte",
    "includes", "exists", "matches", "count_gt", "count_lt",
})


def evaluate_check(check, snapshot):
    """Evaluate a declarative check (PASS condition) against a snapshot root.

    Supports composition via ``all`` / ``any`` / ``not`` (each wrapping child
    checks), or a leaf ``{field, op, value}``. Returns a bool. Missing data
    yields False rather than raising.
    """
    if "all" in check:
        return all(evaluate_check(c, snapshot) for c in check["all"])
    if "any" in check:
        return any(evaluate_check(c, snapshot) for c in check["any"])
    if "not" in check:
        return not evaluate_check(check["not"], snapshot)
    actual = resolve_path(snapshot, check["field"])
    return _apply_op(check["op"], actual, check.get("value"))


def _as_list(actual):
    return actual if isinstance(actual, list) else ([] if actual is None else [actual])


def _numeric(actual, value, fn):
    if isinstance(actual, list) or actual is None or not isinstance(actual, (int, float)):
        return False
    return fn(actual, value)


def _apply_op(op, actual, value):
    if op == "exists":
        return actual is not None and actual != []
    if op == "equals":
        return actual == value
    if op == "gt":
        return _numeric(actual, value, lambda a, b: a > b)
    if op == "lt":
        return _numeric(actual, value, lambda a, b: a < b)
    if op == "gte":
        return _numeric(actual, value, lambda a, b: a >= b)
    if op == "lte":
        return _numeric(actual, value, lambda a, b: a <= b)
    if op == "includes":
        return value in _as_list(actual)
    if op == "matches":
        rx = re.compile(value)
        return any(rx.search(str(x)) for x in _as_list(actual))
    if op == "count_gt":
        return len(_as_list(actual)) > value
    if op == "count_lt":
        return len(_as_list(actual)) < value
    raise ValueError("Unknown op '%s'" % op)


_SCOPE_COLLECTION = {"track": "tracks", "return": "returns"}


def _has_signal(rule, snapshot):
    """True when the audio-tap signal the rule needs is present in the snapshot.

    v1 only meters the master, so any signal_required rule (scope master or set)
    is gated on master.signal being populated.
    """
    return (snapshot.get("master") or {}).get("signal") is not None


def evaluate_rules(rules, snapshot):
    """Run a list of rule dicts against a normalized snapshot.

    Returns ``{findings, manual_rules, deferred_rules, summary}``. ``auto`` rules
    produce findings (status pass/fail/warn/info); ``manual`` rules are surfaced
    for human/Claude judgment; ``deferred`` rules (and ``signal_required`` rules
    whose audio-tap signal is absent) are parked as needing metering.
    """
    findings, manual, deferred = [], [], []
    for rule in rules:
        mode = rule.get("mode", "auto")
        req = rule.get("requires")
        unknown = rule.get("defer_if_null")
        if (req and not resolve_path(snapshot, req)) or (
                unknown and resolve_path(snapshot, unknown) is None):
            # Data the rule needs was not gathered (e.g. plugin_state=False).
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": rule.get("requires_reason", "needs %s" % req)})
            continue
        if rule.get("signal_required") and not _has_signal(rule, snapshot):
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": "needs metering"})
            continue
        if mode == "deferred":
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": "needs metering"})
            continue
        if mode == "manual":
            manual.append({"id": rule["id"], "domain": rule["domain"],
                           "title": rule.get("title", rule["id"]),
                           "rationale": rule.get("rationale", "")})
            continue
        findings.extend(_eval_auto(rule, snapshot))
    return {"findings": findings, "manual_rules": manual,
            "deferred_rules": deferred, "summary": _summarize(findings, manual, deferred)}


def _eval_auto(rule, snapshot):
    scope = rule.get("scope", "set")
    if scope == "set":
        ok = evaluate_check(rule["check"], snapshot)
        return [_finding(rule, ok, _evidence(rule, snapshot))]
    if scope == "master":
        root = snapshot.get("master") or {}
        ok = evaluate_check(rule["check"], root)
        return [_finding(rule, ok, _evidence(rule, root))]
    entities = snapshot.get(_SCOPE_COLLECTION[scope]) or []
    failed = [_finding(rule, False, _evidence(rule, e), entity=e.get("name"))
              for e in entities if not evaluate_check(rule["check"], e)]
    if failed:
        return failed
    return [_finding(rule, True, "all %ss pass" % scope)]


def _finding(rule, ok, evidence, entity=None):
    f = {"id": rule["id"], "domain": rule["domain"],
         "status": "pass" if ok else rule["severity"],
         "severity": rule["severity"], "evidence": evidence,
         "remediation": rule.get("remediation", "")}
    if entity:
        f["entity"] = entity
    return f


def _evidence(rule, root):
    tmpl = rule.get("evidence_template")
    if not tmpl:
        return ""
    return re.sub(r"\{([^}]+)\}", lambda m: str(resolve_path(root, m.group(1))), tmpl)


def _summarize(findings, manual, deferred):
    counts = {"pass": 0, "fail": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    counts["manual"] = len(manual)
    counts["deferred"] = len(deferred)
    return counts


# Live's mixer volume is a 0.0..1.0 linear control where ~0.85 == 0 dB (unity).
# This mirrors Live's fader taper closely enough for gain-staging heuristics.
_UNITY = 0.85
_DB_FLOOR = -70.0


def live_volume_to_db(value):
    """Approximate Live's linear mixer volume (0..1, unity ~0.85) as dB."""
    if value is None or value <= 0.0:
        return _DB_FLOOR
    db = 40.0 * math.log10(value / _UNITY)
    return max(_DB_FLOOR, round(db, 1))


_DB_RE = re.compile(r"(-?inf|-?\d+(?:\.\d+)?)\s*dB", re.I)


def display_db(text):
    """Parse a Live display string ('-6.0 dB', '-inf dB') to a float dB, else None."""
    m = _DB_RE.search(text or "")
    if not m:
        return None
    v = m.group(1).lower()
    if v.endswith("inf"):
        return _DB_FLOOR
    return float(v)


def _norm_devices(raw_devices):
    devices = []
    for d in (raw_devices or []):
        dev = {"index": d.get("index"), "name": d.get("name"),
               "class": d.get("class_name"), "on": d.get("on", True),
               "is_instrument": d.get("is_instrument", False),
               "key_params": d.get("key_params", {})}
        if d.get("automated_params") is not None:
            dev["automated_params"] = d.get("automated_params")
        for k in ("automated", "chain_devices"):
            if d.get(k):
                dev[k] = d.get(k)
        devices.append(dev)
    return devices, [d["name"] for d in devices]


def _norm_sends(raw):
    """Sends as {return, value, display, db} when the remote reports detail;
    falls back to the bare 0..1 list for older remote scripts."""
    detail = raw.get("sends_detail")
    if not detail:
        return None
    return [{"return": s.get("return"), "value": s.get("value"),
             "display": s.get("display"), "db": display_db(s.get("display"))}
            for s in detail]


def _norm_track(raw):
    devices, names = _norm_devices(raw.get("devices"))
    vol_display = raw.get("volume_display")
    track = {
        "index": raw.get("index"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "mixer": {
            # Prefer Live's own fader display over the taper approximation.
            "volume_db": (display_db(vol_display) if display_db(vol_display) is not None
                          else live_volume_to_db(raw.get("volume"))),
            "pan": raw.get("panning", 0.0),
            "sends": raw.get("sends", []),
            "mute": raw.get("mute", False),
            "solo": raw.get("solo", False),
            "arm": raw.get("arm", False),
        },
        "is_grouped": raw.get("is_grouped", False),
        "group_track": raw.get("group_track"),
        "has_instrument": raw.get("has_instrument", False),
        "devices": devices,
        "device_names": names,
        "clips": raw.get("clips", {"count": 0, "named": 0, "warped": 0, "empty_slots": 0}),
        "routing": raw.get("routing", {}),
        "signal": None,
    }
    sends = _norm_sends(raw)
    if sends is not None:
        track["mixer"]["sends_detail"] = sends
    for key in ("arrangement", "automated_mixer"):
        if raw.get(key) is not None:
            track[key] = raw.get(key)
    return track


def derive_limiting(devices):
    """Summarize the limiting stage of a device chain (the master's, usually).

    A native Limiter counts directly (its Ceiling key param, when reported, is
    parsed to dB). An iZotope device counts once its plugin state has been read
    (attach_plugin_states) and a Maximizer/Limiter sits in its active chain.
    Returns {present, source, ceiling_db, true_peak_safe, target_lufs} -
    present=None means "unknown": an iZotope plugin is there but unread."""
    unread_izotope = False
    for d in devices:
        if not d.get("on", True):
            continue
        if d.get("class") == "Limiter" or d.get("name") == "Limiter":
            kp = d.get("key_params") or {}
            return {"present": True, "source": d.get("name"),
                    "ceiling_db": display_db(kp.get("Ceiling")),
                    "true_peak_safe": None, "target_lufs": None}
        iz = d.get("izotope")
        if iz is not None:
            lim = iz.get("limiter")
            if lim and not iz.get("global_bypass"):
                return {"present": True,
                        "source": "%s %s" % (iz.get("product"), lim.get("module")),
                        "ceiling_db": lim.get("ceiling_db"),
                        "true_peak_safe": lim.get("true_peak_safe"),
                        "target_lufs": lim.get("target_lufs")}
        elif any(p in (d.get("name") or "") for p in ("Ozone", "Neutron", "Nectar")):
            unread_izotope = True
    return {"present": None if unread_izotope else False, "source": None,
            "ceiling_db": None, "true_peak_safe": None, "target_lufs": None}


_FAMILY_WORDS = (("Ozone", "Ozone 12"), ("Neutron", "Neutron 5"), ("Nectar", "Nectar 4"))


def _family_of(device_name):
    for word, product in _FAMILY_WORDS:
        if word in (device_name or ""):
            return product
    return None


def attach_plugin_states(snapshot, states):
    """Merge scan_family_states output into a normalized snapshot (in place).

    Each entity gains `plugin_state` (all decoded iZotope instances, document
    order). Top-level devices whose name names an iZotope product get the
    matching instance as `izotope`, paired in order per product (a plugin
    nested in a rack is listed in plugin_state but not paired to a device).
    Recomputes master.limiting and sets snapshot.plugin_state_read = True."""
    def _apply(entity, items):
        entity["plugin_state"] = items
        queues = {}
        for it in items:
            queues.setdefault(it.get("product"), []).append(it)
        for d in entity.get("devices", []):
            if d.get("class") not in (None, "PluginDevice"):
                continue
            prod = _family_of(d.get("name"))
            if prod and queues.get(prod):
                d["izotope"] = queues[prod].pop(0)
        empty = [it for it in items if not it.get("error") and not it.get("chain")]
        entity["izotope_empty_chains"] = len(empty)

    for t in snapshot.get("tracks", []):
        _apply(t, states.get(("regular", t.get("index")), []))
    for r in snapshot.get("returns", []):
        _apply(r, states.get(("return", r.get("index")), []))
    master = snapshot.get("master") or {}
    _apply(master, states.get(("master", 0), []))
    master["limiting"] = derive_limiting(master.get("devices", []))
    snapshot["plugin_state_read"] = True
    return snapshot


def _compact_device(d):
    out = {"name": d.get("name"), "class": d.get("class")}
    if not d.get("on", True):
        out["on"] = False
    if d.get("is_instrument"):
        out["is_instrument"] = True
    for k in ("key_params", "automated", "chain_devices"):
        if d.get(k):
            out[k] = d[k]
    if d.get("izotope"):
        iz = d["izotope"]
        out["izotope"] = {"chain": [c["module"] for c in iz.get("chain", [])
                                    if not c.get("bypass")],
                          "limiter": iz.get("limiter"),
                          "global_bypass": iz.get("global_bypass") or None}
    return out


def _compact_entity(t):
    out = {k: t[k] for k in ("index", "name", "type") if k in t}
    mx = t.get("mixer") or {}
    m = {"volume_db": mx.get("volume_db")}
    if mx.get("pan"):
        m["pan"] = mx["pan"]
    for k in ("mute", "solo", "arm"):
        if mx.get(k):
            m[k] = True
    live_sends = [{"return": s["return"], "db": s["db"]}
                  for s in (mx.get("sends_detail") or []) if s.get("db", -70.0) > -70.0]
    if live_sends:
        m["sends"] = live_sends
    out["mixer"] = m
    if t.get("group_track"):
        out["group_track"] = t["group_track"]
    if t.get("has_instrument"):
        out["has_instrument"] = True
    if t.get("devices"):
        out["devices"] = [_compact_device(d) for d in t["devices"]]
    clips = t.get("clips") or {}
    if clips.get("count"):
        out["clips"] = clips
    for k in ("arrangement", "automated_mixer", "izotope_empty_chains"):
        if t.get(k):
            out[k] = t[k]
    to = (t.get("routing") or {}).get("audio_to")
    if to:
        out["audio_to"] = to
    return out


def compact_snapshot(snapshot):
    """A smaller snapshot for large sets: drops default/empty fields (device
    on=True, is_instrument=False, empty key_params, unused sends, empty Session
    clip counts, null signals, the raw 0..1 send list) but keeps every value a
    rule or a manual judgment reads - fader dB, active sends in dB, device
    key_params/automation/rack contents, iZotope chains and limiters,
    arrangement counts, routing target. Rules must run on the FULL snapshot;
    this is for the response only."""
    master = snapshot.get("master") or {}
    return {
        "transport": snapshot.get("transport"),
        "plugin_state_read": snapshot.get("plugin_state_read", False),
        "tracks": [_compact_entity(t) for t in snapshot.get("tracks", [])],
        "returns": [_compact_entity(r) for r in snapshot.get("returns", [])],
        "master": {"volume_db": master.get("volume_db"),
                   "devices": [_compact_device(d) for d in master.get("devices", [])],
                   "limiting": master.get("limiting"),
                   "signal": master.get("signal")},
    }


def normalize_snapshot(raw):
    """Convert the raw remote payload into the normalized snapshot the rules read."""
    master_raw = raw.get("master") or {}
    m_devices, m_names = _norm_devices(master_raw.get("devices"))
    snap = {
        "transport": {
            "tempo": raw.get("transport", {}).get("tempo"),
            "is_playing": raw.get("transport", {}).get("is_playing", False),
            "time_signature": "%s/%s" % (
                raw.get("transport", {}).get("signature_numerator", 4),
                raw.get("transport", {}).get("signature_denominator", 4)),
        },
        "tracks": [_norm_track(t) for t in raw.get("tracks", [])],
        "returns": [_norm_track(r) for r in raw.get("returns", [])],
        "master": {
            "name": "Master",
            "volume_db": (display_db(master_raw.get("volume_display"))
                          if display_db(master_raw.get("volume_display")) is not None
                          else live_volume_to_db(master_raw.get("volume"))),
            "devices": m_devices,
            "device_names": m_names,
            "signal": None,
            "limiting": derive_limiting(m_devices),
        },
        "plugin_state_read": False,
    }
    return snap
