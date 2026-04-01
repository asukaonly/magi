"""Tests for embedding text builders."""

from magi.memory.embedding.embedding_text_builders import build_l2_edge_embedding_text


class TestBuildL2EdgeEmbeddingText:
    def test_basic_triple(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="LIKES",
            object_id="software:vscode",
        )
        assert text == "user:u1 LIKES software:vscode"

    def test_with_canonical_names(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="LIKES",
            object_id="software:vscode",
            subject_name="用户",
            object_name="VS Code",
        )
        assert text == "用户 LIKES VS Code"

    def test_partial_names_subject_only(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="USES",
            object_id="software:vscode",
            subject_name="用户",
        )
        assert text == "用户 USES software:vscode"

    def test_partial_names_object_only(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="USES",
            object_id="software:vscode",
            object_name="VS Code",
        )
        assert text == "user:u1 USES VS Code"

    def test_with_evidence_and_summary(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="LIKES",
            object_id="topic:anime",
            subject_name="用户",
            object_name="动漫",
            natural_summary="用户喜欢看动漫",
            evidence_text="今天又看了新番",
        )
        lines = text.split("\n")
        assert lines[0] == "用户 LIKES 动漫"
        assert lines[1] == "用户喜欢看动漫"
        assert lines[2] == "今天又看了新番"

    def test_empty_evidence_excluded(self):
        text = build_l2_edge_embedding_text(
            subject_id="user:u1",
            predicate="LIKES",
            object_id="topic:anime",
            evidence_text="",
            natural_summary="",
        )
        assert text == "user:u1 LIKES topic:anime"
