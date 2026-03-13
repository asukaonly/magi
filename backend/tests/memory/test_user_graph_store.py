from magi.memory.l2_user_graph import L2UserGraphStore


def test_user_graph_store_aggregates_edge_evidence_without_duplicates(tmp_path):
    store = L2UserGraphStore(persist_path=str(tmp_path / "user-graph.pkl"))

    store.upsert_node("user:self", "user")
    store.upsert_node("character:asuka", "person", {"name": "Asuka"})
    store.upsert_edge(
        subject_id="user:self",
        predicate="LIKES",
        object_id="character:asuka",
        evidence_event_ids=["timeline-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="browser_history",
    )
    store.upsert_edge(
        subject_id="user:self",
        predicate="LIKES",
        object_id="character:asuka",
        evidence_event_ids=["timeline-1", "timeline-2"],
        confidence=0.9,
        observed_at=1710000600.0,
        source_type="manual_journal",
    )

    edge = store.get_edge("user:self", "LIKES", "character:asuka")

    assert edge is not None
    assert edge.evidence_event_ids == ["timeline-1", "timeline-2"]
    assert edge.first_observed_at == 1710000000.0
    assert edge.last_observed_at == 1710000600.0
    assert edge.source_type_distribution == {"browser_history": 1, "manual_journal": 1}


def test_user_graph_store_filters_edges_by_type(tmp_path):
    store = L2UserGraphStore(persist_path=str(tmp_path / "user-graph.pkl"))

    store.upsert_node("user:self", "user")
    store.upsert_node("topic:eva", "topic")
    store.upsert_node("place:tokyo3", "place")
    store.upsert_edge(
        subject_id="user:self",
        predicate="LIKES",
        object_id="topic:eva",
        evidence_event_ids=["timeline-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="manual_journal",
    )
    store.upsert_edge(
        subject_id="user:self",
        predicate="VISITED",
        object_id="place:tokyo3",
        evidence_event_ids=["timeline-2"],
        confidence=0.7,
        observed_at=1710000100.0,
        source_type="browser_history",
    )

    likes = store.get_edges(predicate="LIKES")
    stats = store.get_statistics()

    assert len(likes) == 1
    assert likes[0].predicate == "LIKES"
    assert stats["total_nodes"] == 3
    assert stats["total_edges"] == 2
