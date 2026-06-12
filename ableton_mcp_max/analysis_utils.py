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
