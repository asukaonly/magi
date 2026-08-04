from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.memory.embedding.embedding_service import EmbeddingResult


class _RecordingEmbeddingService:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_text(self, text: str):
        self.texts.append(text)
        from magi.memory.embedding.embedding_service import EmbeddingResult

        return EmbeddingResult(
            model_name="test-embedding", dimension=4, vector=[1.0, 0.0, 0.0, 0.0]
        )


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.upserted_entity_ids: list[str] = []

    async def upsert(self, *, entity_id: str, embedding, metadata=None) -> None:
        _ = (embedding, metadata)
        self.upserted_entity_ids.append(entity_id)

    async def close(self) -> None:
        return None


class _ControlledEmbeddingService:
    def __init__(self) -> None:
        self.old_embedding_started = asyncio.Event()
        self.release_old_embedding = asyncio.Event()

    async def embed_texts(self, texts: list[str]):
        is_old_snapshot = any("Old Name" in text for text in texts)
        if is_old_snapshot:
            self.old_embedding_started.set()
            await self.release_old_embedding.wait()
        vector = [1.0, 0.0] if is_old_snapshot else [0.0, 1.0]
        return [
            EmbeddingResult(
                model_name="test-embedding",
                dimension=2,
                vector=vector,
            )
            for _ in texts
        ]

    def profile_from_result(self, result, *, text_builder_version: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(profile_id=f"profile:{text_builder_version}")


class _StatefulVectorIndex:
    def __init__(self) -> None:
        self.items: dict[str, EmbeddingResult] = {}

    @asynccontextmanager
    async def rebuild_session(self):
        yield

    async def upsert_many(self, items: list[dict]) -> None:
        for item in items:
            self.items[str(item["entity_id"])] = item["embedding"]

    async def prune_orphans(self, **_kwargs) -> int:
        return 0

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

        await catalog.upsert_entity(
            canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai"
        )
        await catalog.add_alias(entity_id="place:shanghai", alias_text="沪上", confidence=0.6)

        resolved = await catalog.resolve_alias("沪上", entity_type="place")

        assert resolved["decision"] == "unresolved"
        assert resolved["entity_id"] is None
        assert resolved["matched_confidence"] == 0.6


@pytest.mark.asyncio
async def test_canonical_name_is_not_stored_as_its_own_alias() -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="GitHub",
            entity_type="software",
            entity_id="software:github",
        )
        await catalog.add_alias(
            entity_id=entity_id,
            alias_text="github",
            confidence=0.95,
        )

        entities = await catalog.list_entities(limit=10)
        resolved = await catalog.resolve_alias("github", entity_type="software")

        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "GitHub"
        assert entities[0]["aliases"] == []
        assert resolved == {
            "decision": "match",
            "entity_id": "software:github",
            "candidate_count": 1,
            "matched_confidence": 1.0,
        }


@pytest.mark.asyncio
async def test_canonical_resolution_uses_alias_casefolding_without_duplicate_row() -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="Straße",
            entity_type="place",
            entity_id="place:strasse",
        )
        await catalog.add_alias(
            entity_id=entity_id,
            alias_text="STRASSE",
            confidence=0.95,
        )

        entities = await catalog.list_entities(limit=10)
        resolved = await catalog.resolve_alias("STRASSE", entity_type="place")

        assert entities[0]["aliases"] == []
        assert resolved["decision"] == "match"
        assert resolved["entity_id"] == entity_id
        assert resolved["matched_confidence"] == 1.0


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
                        canonical_name_is_independent INTEGER NOT NULL DEFAULT 1,
                        created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 1.0,
                        is_independent INTEGER NOT NULL DEFAULT 1,
                        created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, normalized_alias)
                );
                """
            )
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(
            canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai"
        )
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

        await catalog.upsert_entity(
            canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai"
        )
        await catalog.upsert_entity(
            canonical_name="Shanghai", entity_type="topic", entity_id="topic:shanghai"
        )

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
                        canonical_name_is_independent INTEGER NOT NULL DEFAULT 1,
                        created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 1.0,
                        is_independent INTEGER NOT NULL DEFAULT 1,
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

        assert catalog._vector_index.upserted_entity_ids == [
            "organization:openai",
            "organization:openai",
        ]  # type: ignore[attr-defined]
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


@pytest.mark.asyncio
async def test_entity_rebuild_does_not_chase_rows_inserted_after_its_high_water():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        disabled_catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
        await disabled_catalog.initialize()
        for entity_id in ("organization:a", "organization:c", "organization:z"):
            await disabled_catalog.upsert_entity(
                canonical_name=entity_id,
                entity_type="organization",
                entity_id=entity_id,
            )
        await disabled_catalog.close()

        service = _RecordingEmbeddingService()
        catalog = L2EntityCatalog(db_path=db_path, embedding_service=service)
        await catalog.initialize()

        async def insert_between_existing_ids(processed: int) -> None:
            if processed != 1:
                return
            with sqlite3.connect(db_path) as db:
                db.execute(
                    """
                    INSERT INTO entity_catalog(
                        entity_id, canonical_name, entity_type, created_at, updated_at
                    ) VALUES ('organization:b', 'Inserted During Rebuild', 'organization', 10, 10)
                    """
                )
                db.commit()

        try:
            processed = await catalog.rebuild_embeddings(
                batch_size=1,
                progress_callback=insert_between_existing_ids,
            )
        finally:
            await catalog.close()

        assert processed == 3
        assert all("Inserted During Rebuild" not in text for text in service.texts)


@pytest.mark.asyncio
async def test_entity_rebuild_does_not_overwrite_a_newer_normal_embedding():
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        disabled_catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
        await disabled_catalog.initialize()
        await disabled_catalog.upsert_entity(
            canonical_name="Old Name",
            entity_type="organization",
            entity_id="organization:subject",
        )
        await disabled_catalog.close()

        service = _ControlledEmbeddingService()
        index = _StatefulVectorIndex()
        catalog = L2EntityCatalog(db_path=db_path, embedding_service=service)
        catalog._vector_index = index  # type: ignore[assignment]
        await catalog.initialize()
        rebuild_task = asyncio.create_task(catalog.rebuild_embeddings(batch_size=1))
        try:
            await asyncio.wait_for(service.old_embedding_started.wait(), timeout=1)
            await catalog.upsert_entity(
                canonical_name="New Name",
                entity_type="organization",
                entity_id="organization:subject",
            )
            assert index.items["organization:subject"].vector == [0.0, 1.0]
        finally:
            service.release_old_embedding.set()
            await asyncio.wait_for(rebuild_task, timeout=1)
            await catalog.close()

        assert index.items["organization:subject"].vector == [0.0, 1.0]
