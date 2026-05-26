"""Pure helpers for browser preset selection. No Live dependencies.

Like the other *_utils modules, these run server-side only (the Remote Script
in Live's embedded Python cannot import them). They resolve user-supplied
preset names/paths to the canonical browser item the handler can load directly.
"""


def match_preset(items, name):
    """Resolve a preset name to its browser item dict among `items`.

    `items` is a list of dicts as returned by get_browser_items_at_path /
    get_browser_presets (each has 'name', 'uri', 'is_loadable'). Only loadable
    items are considered. Match order:
      1. exact name match
      2. case-insensitive exact match
      3. unique case-insensitive substring match

    Returns the matching item dict. Raises ValueError (listing the available
    loadable names) on no match, an ambiguous substring, or no loadable items.
    """
    loadable = [i for i in items if i.get("is_loadable")]
    if not loadable:
        raise ValueError("No loadable presets at this path.")

    for i in loadable:
        if i.get("name") == name:
            return i

    lowered = str(name).strip().lower()
    for i in loadable:
        if str(i.get("name", "")).lower() == lowered:
            return i

    substr = [i for i in loadable if lowered in str(i.get("name", "")).lower()]
    if len(substr) == 1:
        return substr[0]

    available = ", ".join(str(i.get("name", "")) for i in loadable)
    if len(substr) > 1:
        matches = ", ".join(str(i.get("name", "")) for i in substr)
        raise ValueError(
            "Preset '%s' is ambiguous; matches: %s. Available: %s"
            % (name, matches, available)
        )
    raise ValueError(
        "Preset '%s' not found. Available: %s" % (name, available)
    )


def _format_names(names, cap=30):
    """Join names for an error message, capping a long list with a tail count."""
    names = [str(n) for n in names]
    if len(names) <= cap:
        return ", ".join(names)
    return ", ".join(names[:cap]) + " ... (+%d more)" % (len(names) - cap)


def match_recursive_preset(presets, query):
    """Resolve `query` against a recursive preset list to a single preset dict.

    `presets` is the list returned by the remote `get_browser_presets` command:
    each dict has 'name', 'relative_path' (e.g. 'Bass/Talking Bass.adv') and
    'uri'. Unlike `match_preset`, this searches the whole subtree, so a leaf
    name surfaced by list_device_presets resolves even when it lives in a
    subfolder. `query` is matched against BOTH 'name' and 'relative_path':
      1. exact match (name or relative_path)
      2. case-insensitive exact match (name or relative_path)
      3. unique case-insensitive substring match (name or relative_path)

    Returns the matching dict. Raises ValueError (listing available presets,
    capped) on no match, an ambiguous substring, or an empty list.
    """
    if not presets:
        raise ValueError("No loadable presets at this path.")

    q = str(query)
    for p in presets:
        if p.get("name") == q or p.get("relative_path") == q:
            return p

    ql = q.strip().lower()
    for p in presets:
        if (str(p.get("name", "")).lower() == ql
                or str(p.get("relative_path", "")).lower() == ql):
            return p

    subs = [
        p for p in presets
        if ql in str(p.get("name", "")).lower()
        or ql in str(p.get("relative_path", "")).lower()
    ]
    if len(subs) == 1:
        return subs[0]

    labels = [p.get("relative_path") or p.get("name") for p in presets]
    if len(subs) > 1:
        matches = [p.get("relative_path") or p.get("name") for p in subs]
        raise ValueError(
            "Preset '%s' is ambiguous; matches: %s"
            % (query, _format_names(matches))
        )
    raise ValueError(
        "Preset '%s' not found. Available: %s" % (query, _format_names(labels))
    )


def split_preset_path(path):
    """Split a full browser path into (parent_path, leaf_name).

    E.g. "instruments/Wavetable/Bass/Talking Bass" ->
         ("instruments/Wavetable/Bass", "Talking Bass").

    Raises ValueError if `path` has no parent segment (a single category like
    "instruments"), since a leaf can't be resolved without a containing folder.
    """
    cleaned = str(path).strip().strip("/")
    if "/" not in cleaned:
        raise ValueError(
            "Path '%s' has no preset leaf; provide 'name' or a deeper path "
            "like 'instruments/Wavetable/<preset>'." % (path,)
        )
    parent, leaf = cleaned.rsplit("/", 1)
    if not leaf:
        raise ValueError("Path '%s' has an empty leaf segment." % (path,))
    return parent, leaf
