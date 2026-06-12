import pytest
from ableton_mcp_max.ruleset_utils import (
    DOMAINS, load_ruleset, load_rulesets, validate_rule, validate_all,
)


def test_all_shipped_rulesets_validate():
    # The drift guard: every shipped rule must pass schema validation, and every
    # `source` anchor must exist in sources.md.
    validate_all()


def test_load_ruleset_returns_list_of_dicts():
    rules = load_ruleset("health")
    assert isinstance(rules, list) and rules
    assert all("id" in r and "domain" in r for r in rules)
    assert all(r["domain"] == "health" for r in rules)


def test_load_rulesets_all_combines_every_domain():
    combined = load_rulesets("all")
    domains = {r["domain"] for r in combined}
    assert domains == set(DOMAINS)


def test_load_rulesets_focus_single_domain():
    combined = load_rulesets("mastering")
    assert {r["domain"] for r in combined} == {"mastering"}


def test_load_rulesets_rejects_unknown_focus():
    with pytest.raises(ValueError):
        load_rulesets("loudness")


def test_validate_rule_rejects_bad_severity():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "boom",
                       "mode": "auto", "scope": "set",
                       "check": {"field": "a", "op": "exists"},
                       "source": "sources.md#health-naming"}, anchors={"health-naming"})


def test_validate_rule_requires_check_for_auto():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "auto", "source": "sources.md#health-naming"},
                      anchors={"health-naming"})


def test_validate_rule_rejects_unknown_op():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "auto", "scope": "set",
                       "check": {"field": "a", "op": "is_blue", "value": 1},
                       "source": "sources.md#health-naming"}, anchors={"health-naming"})


def test_validate_rule_rejects_missing_source_anchor():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "manual", "source": "sources.md#nope"},
                      anchors={"health-naming"})
