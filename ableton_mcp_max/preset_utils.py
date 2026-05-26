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
