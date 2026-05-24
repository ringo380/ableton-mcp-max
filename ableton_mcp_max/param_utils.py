"""Pure helpers for resolving device parameters. No Live dependencies."""


def resolve_parameter_index(parameters, identifier):
    """Resolve a parameter identifier (int index, numeric string, or name)
    to its integer index within `parameters` (a list of dicts with
    'index' and 'name' keys, as returned by get_device_parameters).

    Raises ValueError if it can't be resolved.
    """
    # Integer index or numeric string -> validate range.
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        idx = int(identifier)
        if idx < 0 or idx >= len(parameters):
            raise ValueError(
                "Parameter index %d out of range (0..%d)" % (idx, len(parameters) - 1)
            )
        return idx

    # Exact name match.
    for p in parameters:
        if p.get("name") == identifier:
            return p["index"]

    # Case-insensitive name match.
    lowered = str(identifier).lower()
    for p in parameters:
        if str(p.get("name", "")).lower() == lowered:
            return p["index"]

    names = ", ".join(str(p.get("name", "")) for p in parameters)
    raise ValueError("Parameter '%s' not found. Available: %s" % (identifier, names))
