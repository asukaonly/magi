"""Tests for embedding text builders."""

from magi.memory.embedding.embedding_text_builders import (
    build_l1_embedding_text,
    build_l1_retrieval_terms_text,
    build_l2_edge_embedding_text,
)
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth


class TestBuildL1EmbeddingText:
    def test_uses_embedding_head_when_present(self):
        event = MemoryEvent(
            event_id="evt-1",
            correlation_id="evt-1",
            timestamp=1700000000.0,
            created_at=1700000001.0,
            event_type="SOURCE_EVENT",
            source="photos",
            source_item_id="item-1",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="照片 拍摄 2022-11-27 在湖州拍摄了 1 张照片",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=20,
            metadata_json={
                "projection": {
                    "embedding_head": "照片拍摄",
                }
            },
        )

        assert build_l1_embedding_text(event) == "照片拍摄\n照片 拍摄 2022-11-27 在湖州拍摄了 1 张照片"

    def test_appends_projection_retrieval_terms(self):
        event = MemoryEvent(
            event_id="evt-2",
            correlation_id="evt-2",
            timestamp=1700000000.0,
            created_at=1700000001.0,
            event_type="SOURCE_EVENT",
            source="netease_music",
            source_item_id="item-2",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="网易云音乐听了 YOASOBI 的《夜に駆ける》",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=20,
            metadata_json={
                "projection": {
                    "embedding_head": "网易云音乐听歌",
                    "retrieval_terms": ["j-pop", "electropop", "J-POP"],
                }
            },
        )

        assert build_l1_retrieval_terms_text(event) == "j-pop electropop"
        assert build_l1_embedding_text(event) == (
            "网易云音乐听歌\n"
            "网易云音乐听了 YOASOBI 的《夜に駆ける》\n"
            "j-pop electropop"
        )


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
