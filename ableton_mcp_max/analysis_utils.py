"""Pure analysis helpers for the track-analysis feature. No Live dependencies.

Server-side only (the Remote Script in Live's embedded Python cannot import
this). Provides a dotted-path resolver, a declarative predicate evaluator, and
the rule -> findings engine. Rules are DATA (see ableton_mcp_max/rulesets/*.json);
this module is the fixed engine that runs them.
"""

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


def evaluate_rules(rules, snapshot):
    """Run a list of rule dicts against a normalized snapshot.

    Returns ``{findings, manual_rules, deferred_rules, summary}``. ``auto`` rules
    produce findings (status pass/fail/warn/info); ``manual`` rules are surfaced
    for human/Claude judgment; ``deferred`` (or ``signal_required``) rules are
    parked as needing metering.
    """
    findings, manual, deferred = [], [], []
    for rule in rules:
        mode = rule.get("mode", "auto")
        if rule.get("signal_required") or mode == "deferred":
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
