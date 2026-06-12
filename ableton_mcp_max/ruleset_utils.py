"""Load + schema-validate the curated rulesets. Server-side only.

Rulesets are JSON arrays of rule objects under ableton_mcp_max/rulesets/. This
module is the single loader/validator so a malformed rule fails fast (offline)
rather than at analysis time. `validate_all()` is exercised by the test suite as
the drift guard.
"""

import json
import os
import re

from ableton_mcp_max.analysis_utils import VALID_OPS

DOMAINS = ("mixing", "mastering", "sound_design", "health")
_VALID_SEVERITY = frozenset({"fail", "warn", "info"})
_VALID_MODE = frozenset({"auto", "manual", "deferred"})
_VALID_SCOPE = frozenset({"set", "track", "return", "master"})

_DIR = os.path.join(os.path.dirname(__file__), "rulesets")


def _slug(heading):
    return re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")


def _source_anchors():
    """Anchors defined by '## ' headings in sources.md."""
    path = os.path.join(_DIR, "sources.md")
    anchors = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("## "):
                anchors.add(_slug(line[3:]))
    return anchors


def load_ruleset(domain):
    """Load one domain's rule list (no validation)."""
    if domain not in DOMAINS:
        raise ValueError("Unknown domain '%s'. Valid: %s" % (domain, ", ".join(DOMAINS)))
    with open(os.path.join(_DIR, "%s.json" % domain), "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_rulesets(focus="all"):
    """Load rules for a focus: 'all' or a single domain. Returns a flat list."""
    if focus == "all":
        out = []
        for d in DOMAINS:
            out.extend(load_ruleset(d))
        return out
    if focus not in DOMAINS:
        raise ValueError("Unknown focus '%s'. Valid: all, %s" % (focus, ", ".join(DOMAINS)))
    return load_ruleset(focus)


def _check_ops(check):
    if "all" in check:
        for c in check["all"]:
            _check_ops(c)
        return
    if "any" in check:
        for c in check["any"]:
            _check_ops(c)
        return
    if "not" in check:
        _check_ops(check["not"])
        return
    if check.get("op") not in VALID_OPS:
        raise ValueError("Unknown op '%s'" % check.get("op"))
    if "field" not in check:
        raise ValueError("Leaf check missing 'field'")


def validate_rule(rule, anchors):
    """Raise ValueError if a rule violates the schema."""
    for key in ("id", "domain", "severity", "mode", "source"):
        if key not in rule:
            raise ValueError("Rule missing '%s': %r" % (key, rule.get("id", rule)))
    if rule["severity"] not in _VALID_SEVERITY:
        raise ValueError("Rule %s bad severity '%s'" % (rule["id"], rule["severity"]))
    if rule["mode"] not in _VALID_MODE:
        raise ValueError("Rule %s bad mode '%s'" % (rule["id"], rule["mode"]))
    if rule["mode"] == "auto":
        if "check" not in rule:
            raise ValueError("Auto rule %s missing 'check'" % rule["id"])
        if rule.get("scope", "set") not in _VALID_SCOPE:
            raise ValueError("Rule %s bad scope '%s'" % (rule["id"], rule.get("scope")))
        _check_ops(rule["check"])
    anchor = rule["source"].split("#", 1)[-1]
    if anchor not in anchors:
        raise ValueError("Rule %s source anchor '%s' not in sources.md" % (rule["id"], anchor))


def validate_all():
    """Validate every shipped ruleset. Raises on the first violation."""
    anchors = _source_anchors()
    seen = set()
    for domain in DOMAINS:
        for rule in load_ruleset(domain):
            if rule.get("domain") != domain:
                raise ValueError("Rule %s in %s.json has domain '%s'"
                                 % (rule.get("id"), domain, rule.get("domain")))
            if rule["id"] in seen:
                raise ValueError("Duplicate rule id '%s'" % rule["id"])
            seen.add(rule["id"])
            validate_rule(rule, anchors)
