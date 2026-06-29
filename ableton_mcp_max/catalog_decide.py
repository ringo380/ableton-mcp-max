"""Decision engine: reuse-vs-create over the catalog, plus dispatch resolution.

Propose only - recommend() never writes. resolve_dispatch() maps a create plan to
the existing creator server.py should call; the actual invocation lives in
server.py (it needs the Ableton connection).
"""
from ableton_mcp_max import catalog_query

REUSE_MIN_SCORE = 2

_CREATABLE = {"serum", "wavetable", "simpler"}
# domains whose similarity runs against device_preset rows
_QUERY_DOMAIN = {"wavetable": "device_preset", "simpler": "device_preset"}
_VALID_CREATORS = {"create_wavetable_preset", "create_simpler_instrument",
                   "serum_clone"}


def _make_plan(domain, intent, top):
    name = (intent or "Untitled").strip()[:48] or "Untitled"
    if domain == "serum":
        base = top[0]["path"] if top else None
        return {"tool": "serum_clone", "params": {"name": name},
                "base_preset": base}
    if domain == "wavetable":
        return {"tool": "create_wavetable_preset",
                "params": {"name": name, "table1": "Basics"}, "base_preset": None}
    if domain == "simpler":
        return {"tool": "create_simpler_instrument",
                "params": {"name": name, "sample_path": None}, "base_preset": None}
    return None


def recommend(conn, intent, domain):
    """Propose reuse-vs-create for a described asset.

    Args:
        conn: Catalog database connection.
        intent: User's description of the desired asset.
        domain: One of 'serum', 'sample', 'groove', 'device_preset', 'wavetable', 'simpler'.
                For 'wavetable' and 'simpler', similarity search runs against 'device_preset'
                rows since the catalog has no rows for Ableton device presets yet.

    Returns:
        dict with keys:
            - decision: 'reuse' if top match >= REUSE_MIN_SCORE; 'create' if creatable;
                       'gap' otherwise.
            - top_matches: Up to 5 similar items from the catalog.
            - create_plan: Plan dict (only if decision == 'create'); None otherwise.
            - reason: Human-readable explanation.
    """
    qdomain = _QUERY_DOMAIN.get(domain, domain)
    matches = catalog_query.find_similar(conn, intent, qdomain, limit=5)
    top = matches
    top_score = top[0]["score"] if top else 0
    if top_score >= REUSE_MIN_SCORE:
        return {"decision": "reuse", "top_matches": top, "create_plan": None,
                "reason": "Top match scored %d (>= %d)." % (top_score, REUSE_MIN_SCORE)}
    if domain in _CREATABLE:
        return {"decision": "create", "top_matches": top,
                "create_plan": _make_plan(domain, intent, top),
                "reason": "No match scored >= %d; proposing a new %s."
                          % (REUSE_MIN_SCORE, domain)}
    return {"decision": "gap", "top_matches": top, "create_plan": None,
            "reason": "No match and %s assets cannot be synthesized." % domain}


def resolve_dispatch(plan):
    """Map a create plan to the resolved creator and kwargs.

    Args:
        plan: Create plan dict from recommend(). Must have:
            - tool: One of 'create_wavetable_preset', 'create_simpler_instrument', 'serum_clone'.
            - params: Dict of keyword arguments.
            - base_preset: (serum_clone only) Path to base preset; required for serum_clone.
            - fx_edits: (serum_clone only, optional) List of FX edits to apply.

    Returns:
        dict with keys:
            - creator: Tool name to invoke.
            - kwargs: Keyword arguments to pass to the creator.

    Raises:
        ValueError: If plan is invalid or missing required fields.
    """
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    tool = plan.get("tool")
    if tool not in _VALID_CREATORS:
        raise ValueError("unknown create tool: %r (valid: %s)"
                         % (tool, ", ".join(sorted(_VALID_CREATORS))))
    params = plan.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("plan.params must be an object")
    out = {"creator": tool, "kwargs": dict(params)}
    if tool == "serum_clone":
        base = plan.get("base_preset")
        if not base:
            raise ValueError("serum_clone requires base_preset")
        out["kwargs"]["base_preset"] = base
        if plan.get("fx_edits"):
            out["kwargs"]["fx_edits"] = plan["fx_edits"]
    return out
