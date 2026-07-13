import ableton_mcp_max.master_ozone_utils as mou


def _dev(index, name, is_on=True):
    return {"index": index, "name": name, "is_on": is_on}


def test_empty_master_requires_load():
    plan = mou.plan_master_ozone([])
    assert plan == {"target_index": None, "action": "loaded",
                    "disable_indices": [], "load_required": True}


def test_only_ozone12_on_is_reused():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 12", True)])
    assert plan["action"] == "reused"
    assert plan["target_index"] == 0
    assert plan["disable_indices"] == []
    assert plan["load_required"] is False


def test_only_ozone12_off_is_reenabled():
    plan = mou.plan_master_ozone([_dev(2, "Ozone 12", False)])
    assert plan["action"] == "reused_reenabled"
    assert plan["target_index"] == 2
    assert plan["load_required"] is False


def test_only_older_ozone_loads_and_disables():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 10", True)])
    assert plan["action"] == "loaded"
    assert plan["load_required"] is True
    assert plan["disable_indices"] == [0]
    assert plan["target_index"] is None


def test_mixed_older_and_12_reuses_and_disables_older():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 9", True),
                                  _dev(1, "Ozone 12", True)])
    assert plan["action"] == "reused"
    assert plan["target_index"] == 1
    assert plan["disable_indices"] == [0]
    assert plan["load_required"] is False


def test_multiple_ozone12_picks_lowest_index():
    plan = mou.plan_master_ozone([_dev(3, "Ozone 12", True),
                                  _dev(1, "Ozone 12", True)])
    assert plan["target_index"] == 1


def test_component_plugins_do_not_match():
    devices = [_dev(0, "Ozone 12 Maximizer", True),
               _dev(1, "Ozone 12 Equalizer", True)]
    plan = mou.plan_master_ozone(devices)
    assert plan["action"] == "loaded"
    assert plan["load_required"] is True
    assert plan["disable_indices"] == []
    assert plan["target_index"] is None


def test_name_matched_exactly_after_strip():
    # Trailing space is stripped; lower-case is NOT a canonical Live name.
    assert mou.plan_master_ozone([_dev(0, "Ozone 12 ", True)])["action"] == "reused"
    assert mou.plan_master_ozone([_dev(0, "ozone 12", True)])["load_required"] is True


def test_none_name_is_safe():
    plan = mou.plan_master_ozone([_dev(0, None, True)])
    assert plan["load_required"] is True


def test_pick_loaded_target_finds_new_ozone12():
    before = [_dev(0, "Ozone 10", False), _dev(1, "MCP Tap", True)]
    after = [_dev(0, "Ozone 10", False), _dev(1, "MCP Tap", True),
             _dev(2, "Ozone 12", True)]
    assert mou.pick_loaded_target(before, after) == 2


def test_pick_loaded_target_none_when_no_new():
    before = [_dev(0, "Ozone 12", True)]
    after = [_dev(0, "Ozone 12", True)]
    assert mou.pick_loaded_target(before, after) == 0  # fallback: lowest present


def test_pick_loaded_target_none_when_absent():
    assert mou.pick_loaded_target([], []) is None
