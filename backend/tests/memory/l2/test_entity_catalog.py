from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class _RecordingEmbeddingService:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_text(self, text: str):
        self.texts.append(text)
        from magi.memory.embedding.embedding_service import EmbeddingResult

        return EmbeddingResult(model_name="test-embedding", dimension=4, vector=[1.0, 0.0, 0.0, 0.0])


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.upserted_entity_ids: list[str] = []

    async def upsert(self, *, entity_id: str, embedding, metadata=None) -> None:
        _ = (embedding, metadata)
        self.upserted_entity_ids.append(entity_id)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_exact_alias_mapping_resolves_shanghai_and_modu_to_same_entity():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="Shanghai",
            entity_type="place",
            entity_id="place:shanghai",
        )
        await catalog.add_alias(entity_id=entity_id, alias_text="上海", confidence=1.0)
        await catalog.add_alias(entity_id=entity_id, alias_text="魔都", confidence=0.95)

        resolved_shanghai = await catalog.resolve_alias("上海", entity_type="place")
        resolved_modu = await catalog.resolve_alias("魔都", entity_type="place")

        assert resolved_shanghai["decision"] == "match"
        assert resolved_shanghai["entity_id"] == "place:shanghai"
        assert resolved_modu["decision"] == "match"
        assert resolved_modu["entity_id"] == "place:shanghai"


@pytest.mark.asyncio
async def test_ambiguous_alias_returns_unresolved():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        organization_id = await catalog.upsert_entity(
            canonical_name="Apple Inc.",
            entity_type="organization",
            entity_id="org:apple",
        )
        food_id = await catalog.upsert_entity(
            canonical_name="Apple Fruit",
            entity_type="food",
            entity_id="food:apple",
        )
        await catalog.add_alias(entity_id=organization_id, alias_text="apple", confidence=0.92)
        await catalog.add_alias(entity_id=food_id, alias_text="apple", confidence=0.91)

        resolved = await catalog.resolve_alias("apple")

        assert resolved["decision"] == "unresolved"
        assert resolved["entity_id"] is None
        assert resolved["candidate_count"] == 2


@pytest.mark.asyncio
async def test_low_confidence_alias_does_not_auto_merge():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai")
        await catalog.add_alias(entity_id="place:shanghai", alias_text="沪上", confidence=0.6)

        resolved = await catalog.resolve_alias("沪上", entity_type="place")

        assert resolved["decision"] == "unresolved"
        assert resolved["entity_id"] is None
        assert resolved["matched_confidence"] == 0.6


@pytest.mark.asyncio
async def test_record_mention_preserves_surface_form_and_evidence_event_ids():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()
        await catalog.upsert_entity(
            canonical_name="Shanghai",
            entity_type="place",
            entity_id="place:shanghai",
        )

        mention_id = await catalog.record_mention(
            mention_text="魔都",
            normalized_surface="魔都",
            entity_type="place",
            evidence_event_ids=["evt-1", "evt-2"],
            evidence_text="我很喜欢魔都",
            resolved_entity_id="place:shanghai",
            confidence=0.95,
        )

        mention = await catalog.get_mention(mention_id)

        assert mention["mention_text"] == "魔都"
        assert mention["normalized_surface"] == "魔都"
        assert mention["evidence_event_ids"] == ["evt-1", "evt-2"]
        assert mention["resolved_entity_id"] == "place:shanghai"


@pytest.mark.asyncio
async def test_list_entities_returns_canonical_names_and_aliases():
    from magi.core.sqlite import sqlite_connection_async
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        async with sqlite_connection_async(db_path) as db:
            await db.executescript(
                """
                CREATE TABLE entity_catalog (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'disabled',
                    embedding_profile_id TEXT,
                    last_embedded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, normalized_alias)
                );
                """
            )
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai")
        await catalog.add_alias(entity_id="place:shanghai", alias_text="上海", confidence=1.0)
        await catalog.add_alias(entity_id="place:shanghai", alias_text="魔都", confidence=0.95)

        entities = await catalog.list_entities(limit=10)

        assert len(entities) == 1
        assert entities[0] == {
            "entity_id": "place:shanghai",
            "canonical_name": "Shanghai",
            "entity_type": "place",
            "embedding_status": "disabled",
            "embedding_profile_id": None,
            "last_embedded_at": None,
            "created_at": entities[0]["created_at"],
            "updated_at": entities[0]["updated_at"],
            "aliases": ["上海", "魔都"],
        }
        assert entities[0]["created_at"] > 0
        assert entities[0]["updated_at"] > 0


@pytest.mark.asyncio
async def test_find_by_canonical_name_matches_case_insensitively_and_filters_type():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai")
        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="topic", entity_id="topic:shanghai")

        matches = await catalog.find_by_canonical_name("sHaNgHaI")
        place_matches = await catalog.find_by_canonical_name("SHANGHAI", entity_type="place")

        assert [item["entity_id"] for item in matches] == ["topic:shanghai", "place:shanghai"]
        assert place_matches == [
            {
                "entity_id": "place:shanghai",
                "canonical_name": "Shanghai",
                "entity_type": "place",
            }
        ]


@pytest.mark.asyncio
async def test_find_resolution_candidates_prefers_semantic_hits_before_recent_fallback():
    from magi.core.sqlite import sqlite_connection_async
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        async with sqlite_connection_async(db_path) as db:
            await db.executescript(
                """
                CREATE TABLE entity_catalog (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'disabled',
                    embedding_profile_id TEXT,
                    last_embedded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, normalized_alias)
                );
                """
            )
            await db.commit()
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(
            canonical_name="Wurm Hunger",
            entity_type="media",
            entity_id="media:wurm-hunger",
        )
        await catalog.upsert_entity(
            canonical_name="Recent Show",
            entity_type="media",
            entity_id="media:recent-show",
        )
        semantic_queries: list[tuple[str, int]] = []

        async def fake_semantic_search(query_text: str, *, limit: int = 10):
            semantic_queries.append((query_text, limit))
            return [
                {
                    "entity_id": "media:wurm-hunger",
                    "canonical_name": "Wurm Hunger",
                    "entity_type": "media",
                }
            ]

        catalog.search_entities_semantic = fake_semantic_search  # type: ignore[method-assign]

        candidates = await catalog.find_resolution_candidates(
            "蠕动的饥饿",
            entity_type="media",
            limit=2,
        )

        assert semantic_queries == [("蠕动的饥饿", 2)]
        assert [candidate["entity_id"] for candidate in candidates] == [
            "media:wurm-hunger",
            "media:recent-show",
        ]


@pytest.mark.asyncio
async def test_upsert_entity_normalizes_alias_entity_type_before_persistence():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="West Lake Vinegar Fish",
            entity_type="dish",
            entity_id="dish:west-lake-vinegar-fish",
        )
        entities = await catalog.list_entities(limit=10)

        assert entity_id == "food:west-lake-vinegar-fish"
        # Rows now carry created_at/updated_at timestamps; compare the
        # deterministic fields.
        assert len(entities) == 1
        row = dict(entities[0])
        assert row.pop("created_at") > 0
        assert row.pop("updated_at") > 0
        assert row == {
            "entity_id": "food:west-lake-vinegar-fish",
            "canonical_name": "West Lake Vinegar Fish",
            "entity_type": "food",
            "embedding_status": "disabled",
            "embedding_profile_id": None,
            "last_embedded_at": None,
            "aliases": [],
        }


@pytest.mark.asyncio
async def test_record_mention_normalizes_unknown_entity_type_to_other():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        mention_id = await catalog.record_mention(
            mention_text="MysteryThing",
            normalized_surface="mysterything",
            entity_type="unknown_type",
            evidence_event_ids=["evt-1"],
            evidence_text="I saw MysteryThing",
            resolved_entity_id=None,
            confidence=0.4,
        )

        mention = await catalog.get_mention(mention_id)

        assert mention["entity_type"] == "other"


@pytest.mark.asyncio
async def test_entity_embeddings_use_unified_builder_with_aliases_and_remain_single_chunk():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        embedding_service = _RecordingEmbeddingService()
        catalog = L2EntityCatalog(db_path=db_path, embedding_service=embedding_service)
        await catalog.initialize()
        catalog._vector_index = _RecordingVectorIndex()  # type: ignore[assignment]

        entity_id = await catalog.upsert_entity(
            canonical_name="OpenAI",
            entity_type="organization",
            entity_id="org:openai",
        )
        await catalog.add_alias(entity_id=entity_id, alias_text="OpenAI Labs", confidence=0.95)

        assert catalog._vector_index.upserted_entity_ids == ["organization:openai", "organization:openai"]  # type: ignore[attr-defined]
        assert embedding_service.texts[-1] == "organization\nOpenAI\nOpenAI Labs"


@pytest.mark.asyncio
async def test_entity_catalog_exposes_embedding_status_and_profile_id():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        embedding_service = _RecordingEmbeddingService()
        catalog = L2EntityCatalog(db_path=db_path, embedding_service=embedding_service)
        await catalog.initialize()
        try:
            await catalog.upsert_entity(
                canonical_name="OpenAI",
                entity_type="organization",
                entity_id="org:openai",
            )

            entities = await catalog.list_entities(limit=10)

            assert entities[0]["embedding_status"] == "ready"
            assert entities[0]["embedding_profile_id"] is not None
        finally:
            await catalog.close()


@pytest.mark.asyncio
async def test_entity_catalog_rebuild_embeddings_reindexes_disabled_entities():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        disabled_catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
        await disabled_catalog.initialize()
        await disabled_catalog.upsert_entity(
            canonical_name="OpenAI",
            entity_type="organization",
            entity_id="org:openai",
        )
        await disabled_catalog.close()

        rebuild_catalog = L2EntityCatalog(
            db_path=db_path,
            embedding_service=_RecordingEmbeddingService(),
        )
        await rebuild_catalog.initialize()
        try:
            processed = await rebuild_catalog.rebuild_embeddings(batch_size=10)
            entities = await rebuild_catalog.list_entities(limit=10)
        finally:
            await rebuild_catalog.close()

        assert processed == 1
        assert entities[0]["embedding_status"] == "ready"
        assert entities[0]["embedding_profile_id"] is not None
        assert entities[0]["last_embedded_at"] is not None
