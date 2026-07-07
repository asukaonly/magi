from magi.memory.hybrid_retrieval.mode_registry import MODE_REGISTRY


def test_every_mode_has_layer_quota():
    for name, plan in MODE_REGISTRY.items():
        assert plan.layer_quota, f"{name} missing layer_quota"
        assert all(isinstance(v, int) and v >= 0 for v in plan.layer_quota.values())


def test_enumerate_mode_gets_more_l1_l2_than_single_point():
    cross = MODE_REGISTRY["cross_session"].layer_quota
    state = MODE_REGISTRY["current_state"].layer_quota
    assert cross.get("L1", 0) > state.get("L1", 0)
    assert cross.get("L2", 0) >= state.get("L2", 0)


def test_event_stream_is_l1_heavy():
    q = MODE_REGISTRY["event_stream"].layer_quota
    assert q.get("L1", 0) >= 12


def test_experience_recall_uses_l2_with_l1_fallback():
    plan = MODE_REGISTRY["experience_recall"]

    assert plan.primary_layers == ["L2", "L1"]
    assert "experience" in plan.retrieval_units
    assert "episode" not in plan.retrieval_units
    assert plan.layer_quota and plan.layer_quota.get("L2", 0) >= 4


def test_episode_recall_does_not_declare_episode_substrate_retrieval():
    plan = MODE_REGISTRY["episode_recall"]

    assert plan.primary_layers == ["L2", "L1"]
    assert "experience" in plan.retrieval_units
    assert "episode" not in plan.retrieval_units


def test_user_recall_modes_do_not_advertise_episode_substrate_units():
    for mode in ("episode_recall", "experience_recall", "cross_session", "temporal_compare"):
        plan = MODE_REGISTRY[mode]

        assert all("episode" not in unit for unit in plan.retrieval_units)
