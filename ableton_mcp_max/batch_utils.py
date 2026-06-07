"""Validation for the `batch` command (Phase B).

Server-side pure helper (imported by server.py only). The Remote Script runs each
batch member through its single main-thread dispatch table, which only knows the
state-mutating command types, so a batch may only contain those. Reads (get_*)
and a nested `batch` are rejected here with a clear message before the round-trip.
"""

# Hard cap so a runaway batch can't monopolize Live's main thread / blow the
# socket timeout. Generous relative to any real authoring sequence.
MAX_BATCH_COMMANDS = 64


def validate_batch(commands, allowed_types):
    """Validate + normalize a batch member list.

    Parameters:
    - commands: the raw list of {"type", "params"} members from the tool call.
    - allowed_types: the set of batchable (state-mutating) command names
      (server.MUTATING_COMMANDS).

    Returns a new list of normalized {"type": str, "params": dict} members.
    Raises ValueError with an actionable message on any problem.
    """
    if not isinstance(commands, (list, tuple)):
        raise ValueError("batch 'commands' must be a list of {type, params} "
                         "objects")
    if not commands:
        raise ValueError("batch 'commands' must be non-empty")
    if len(commands) > MAX_BATCH_COMMANDS:
        raise ValueError(
            "batch too large: %d commands (max %d)"
            % (len(commands), MAX_BATCH_COMMANDS))

    normalized = []
    for i, c in enumerate(commands):
        if not isinstance(c, dict):
            raise ValueError(
                "batch command %d must be an object with a 'type'" % i)
        t = c.get("type")
        if not isinstance(t, str) or not t:
            raise ValueError(
                "batch command %d is missing a 'type' string" % i)
        if t == "batch":
            raise ValueError(
                "batch command %d: nested batch is not allowed" % i)
        if t not in allowed_types:
            raise ValueError(
                "batch command %d: '%s' is not a batchable (state-mutating) "
                "command; only mutations run in a batch (reads are not "
                "supported)" % (i, t))
        p = c.get("params", {})
        if p is None:
            p = {}
        if not isinstance(p, dict):
            raise ValueError(
                "batch command %d 'params' must be an object" % i)
        normalized.append({"type": t, "params": p})
    return normalized


def coerce_stop_on_error(value):
    """None -> True (default); otherwise truthiness."""
    if value is None:
        return True
    return bool(value)
