"""Tests for FTS5 index integration with L1EventStore and fts_utils."""

from __future__ import annotations

import asyncio
import tempfile
import time

import aiosqlite
import pytest

from magi.memory.hybrid_retrieval.fts_utils import (
    _stem_english_token,
    build_or_fts_query,
    build_stemmed_fts_query,
    escape_fts_query,
    tokenize_for_fts,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l1.event_store import L1EventStore


# ---------------------------------------------------------------------------
# fts_utils unit tests
# ---------------------------------------------------------------------------


class TestTokenizeForFts:
    def test_chinese_text(self) -> None:
        result = tokenize_for_fts("今天天气不错，我想去公园散步")
        assert isinstance(result, str)
        assert len(result) > 0
        # jieba should produce space-separated tokens
        assert " " in result

    def test_english_text(self) -> None:
        result = tokenize_for_fts("The quick brown fox jumps")
        assert "quick" in result
        assert "brown" in result

    def test_mixed_language(self) -> None:
        result = tokenize_for_fts("我在学习Python编程")
        assert isinstance(result, str)
        assert "Python" in result

    def test_empty_string(self) -> None:
        assert tokenize_for_fts("") == ""

    def test_whitespace_only(self) -> None:
        assert tokenize_for_fts("   ") == ""

    def test_none_like(self) -> None:
        assert tokenize_for_fts("") == ""


class TestEscapeFtsQuery:
    def test_strips_asterisk(self) -> None:
        assert "*" not in escape_fts_query("hello*world")

    def test_strips_quotes(self) -> None:
        assert '"' not in escape_fts_query('"exact phrase"')

    def test_strips_parens(self) -> None:
        result = escape_fts_query("(hello OR world)")
        assert "(" not in result
        assert ")" not in result

    def test_preserves_normal_text(self) -> None:
        assert escape_fts_query("hello world") == "hello world"

    def test_collapses_spaces(self) -> None:
        result = escape_fts_query("hello   +  world")
        assert result == "hello world"

    def test_empty_input(self) -> None:
        assert escape_fts_query("") == ""

    def test_special_chars_only(self) -> None:
        assert escape_fts_query("***") == ""


class TestStemEnglishToken:
    def test_strips_ed_suffix(self) -> None:
        assert _stem_english_token("graduated") == "graduat"

    def test_strips_ing_suffix(self) -> None:
        assert _stem_english_token("running") == "run"

    def test_strips_s_suffix(self) -> None:
        assert _stem_english_token("books") == "book"

    def test_strips_ies_suffix(self) -> None:
        assert _stem_english_token("studies") == "study"

    def test_strips_es_suffix(self) -> None:
        assert _stem_english_token("watches") == "watch"

    def test_short_words_unchanged(self) -> None:
        assert _stem_english_token("the") == "the"
        assert _stem_english_token("go") == "go"

    def test_no_suffix_unchanged(self) -> None:
        assert _stem_english_token("degree") == "degree"

    def test_doubled_consonant_ed(self) -> None:
        assert _stem_english_token("stopped") == "stop"

    def test_doubled_consonant_ing(self) -> None:
        assert _stem_english_token("swimming") == "swim"

    def test_ing_simple_strip(self) -> None:
        # No e-restoration: prefix matching handles it (mak* matches make)
        assert _stem_english_token("making") == "mak"
        assert _stem_english_token("learning") == "learn"


class TestBuildStemmedFtsQuery:
    def test_removes_stop_words(self) -> None:
        result = build_stemmed_fts_query("What degree did I graduate with")
        assert "what" not in result.lower().split()
        assert "did" not in result.lower().split()
        assert "with" not in result.lower().split()

    def test_uses_prefix_for_stemmed_tokens(self) -> None:
        result = build_stemmed_fts_query("What degree did I graduate with")
        # "graduate" → unstemmed but >4 chars → chop last → "graduat*"
        assert "graduat*" in result
        # "degree" → unstemmed but >4 chars → "degre*"
        assert "degre*" in result

    def test_empty_after_stop_words(self) -> None:
        result = build_stemmed_fts_query("the a an")
        assert result == ""

    def test_short_latin_tokens_exact(self) -> None:
        result = build_stemmed_fts_query("run fast")
        assert "run" in result
        assert "fast" in result

    def test_stemmed_prefix_matches_inflections(self) -> None:
        result = build_stemmed_fts_query("machine learning optimization")
        # "machine" unstemmed >4 → "machin*"
        assert "machin*" in result
        # "learning" stemmed → "learn*"
        assert "learn*" in result


class TestBuildOrFtsQuery:
    def test_removes_stop_words(self) -> None:
        result = build_or_fts_query("What degree did I graduate with")
        assert "what" not in result.lower()
        assert "did" not in result.lower().split(" OR ")

    def test_includes_prefix_stems(self) -> None:
        result = build_or_fts_query("What degree did I graduate with")
        assert "graduat*" in result
        assert "degre*" in result
        assert " OR " in result

    def test_empty_after_stop_words(self) -> None:
        result = build_or_fts_query("the a an")
        assert result == ""


# ---------------------------------------------------------------------------
# FTS5 integration tests with L1EventStore
# ---------------------------------------------------------------------------

def _make_event(
    event_id: str = "evt-001",
    content: str = "test event content",
    source: str = "test",
    memory_domain: MemoryDomain = MemoryDomain.USER_AUTHORED,
    timestamp: float | None = None,
) -> MemoryEvent:
    now = timestamp or time.time()
    return MemoryEvent(
        event_id=event_id,
        correlation_id="corr-001",
        timestamp=now,
        created_at=now,
        event_type="TestEvent",
        source=source,
        source_item_id=None,
        memory_domain=memory_domain,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content=content,
        author_type="external",
        content_type="text",
        importance_score=0.5,
        level=1,
    )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_l1.db"
    return L1EventStore(db_path=str(db), vector_enabled=False)


@pytest.mark.asyncio
class TestFts5TableCreation:
    async def test_fts_table_exists_after_init(self, store: L1EventStore) -> None:
        await store.initialize()
        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='l1_events_fts'"
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "l1_events_fts"


@pytest.mark.asyncio
class TestFts5WriteSync:
    async def test_store_writes_to_fts(self, store: L1EventStore) -> None:
        event = _make_event(content="机器学习性能优化方案讨论")
        await store.store(event)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT event_id, content FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row[0] == event.event_id
        # FTS content should be tokenized (not identical to raw)
        assert isinstance(row[1], str)
        assert len(row[1]) > 0

    async def test_store_replace_updates_fts(self, store: L1EventStore) -> None:
        event = _make_event(content="original content")
        await store.store(event)

        # Store again with different content (INSERT OR REPLACE)
        event2 = _make_event(content="updated content")
        await store.store(event2)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        assert row[0] == 1  # Only one FTS entry

    async def test_multiple_events_in_fts(self, store: L1EventStore) -> None:
        for i in range(5):
            event = _make_event(
                event_id=f"evt-{i:03d}",
                content=f"Event number {i} with content",
            )
            await store.store(event)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l1_events_fts") as cursor:
                row = await cursor.fetchone()
        assert row[0] == 5


@pytest.mark.asyncio
class TestFts5DeleteSync:
    async def test_mark_deleted_removes_from_fts(self, store: L1EventStore) -> None:
        event = _make_event(content="content to be deleted")
        await store.store(event)

        await store.mark_deleted(event.event_id)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        assert row[0] == 0

    async def test_clear_removes_all_fts(self, store: L1EventStore) -> None:
        for i in range(3):
            await store.store(_make_event(
                event_id=f"evt-{i:03d}",
                content=f"content {i}",
            ))

        await store.clear()

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l1_events_fts") as cursor:
                row = await cursor.fetchone()
        assert row[0] == 0


@pytest.mark.asyncio
class TestBm25Search:
    async def test_basic_bm25_search(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-ml", content="机器学习模型训练优化"))
        await store.store(_make_event(event_id="evt-web", content="前端网页开发React组件"))
        await store.store(_make_event(event_id="evt-db", content="数据库性能调优方案"))

        results = await store.bm25_search("机器学习", limit=10)
        assert len(results) > 0
        event_ids = [r[0] for r in results]
        assert "evt-ml" in event_ids

    async def test_bm25_search_english(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-py", content="Python programming tutorial"))
        await store.store(_make_event(event_id="evt-js", content="JavaScript web development"))

        results = await store.bm25_search("Python", limit=10)
        assert len(results) > 0
        assert results[0][0] == "evt-py"

    async def test_bm25_search_ignores_question_mark_syntax(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-py", content="Python programming tutorial"))

        results = await store.bm25_search("Python?", limit=10)

        assert len(results) > 0
        assert results[0][0] == "evt-py"

    async def test_bm25_search_ignores_single_quote_syntax(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-py", content="Python programming tutorial"))

        results = await store.bm25_search("Python'", limit=10)

        assert len(results) > 0
        assert results[0][0] == "evt-py"

    async def test_bm25_search_ignores_comparison_query_punctuation(self, store: L1EventStore) -> None:
        await store.store(
            _make_event(
                event_id="evt-workshop",
                content="I attended the Effective Time Management workshop at the local community center.",
            )
        )
        await store.store(
            _make_event(
                event_id="evt-webinar",
                content="I participated in the Data Analysis using Python webinar two months ago.",
            )
        )

        results = await store.bm25_search(
            "Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
            limit=10,
        )

        event_ids = [event_id for event_id, _ in results]
        assert "evt-workshop" in event_ids
        assert "evt-webinar" in event_ids

    async def test_bm25_search_empty_query(self, store: L1EventStore) -> None:
        await store.store(_make_event(content="some content"))
        results = await store.bm25_search("", limit=10)
        assert results == []

    async def test_bm25_search_no_match(self, store: L1EventStore) -> None:
        await store.store(_make_event(content="hello world"))
        results = await store.bm25_search("quantumphysics", limit=10)
        assert results == []

    async def test_bm25_search_stemming_matches_inflections(self, store: L1EventStore) -> None:
        """Stemmed AND query should match 'graduated' when searching 'graduate'."""
        await store.store(
            _make_event(
                event_id="evt-degree",
                content="I graduated with a degree in Business Administration",
            )
        )
        await store.store(
            _make_event(
                event_id="evt-other",
                content="The podcast episode discussed the latest technology trends",
            )
        )

        results = await store.bm25_search("What degree did I graduate with", limit=10)
        assert len(results) > 0
        event_ids = [r[0] for r in results]
        assert "evt-degree" in event_ids

    async def test_bm25_returns_scores(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-1", content="machine learning deep learning"))

        results = await store.bm25_search("machine learning", limit=10)
        assert len(results) > 0
        event_id, score = results[0]
        assert isinstance(score, float)

    async def test_bm25_respects_limit(self, store: L1EventStore) -> None:
        for i in range(10):
            await store.store(_make_event(
                event_id=f"evt-{i:03d}",
                content=f"common keyword shared content {i}",
            ))

        results = await store.bm25_search("common keyword", limit=3)
        assert len(results) <= 3


@pytest.mark.asyncio
class TestBackfillFts:
    async def test_backfill_indexes_existing_events(self, store: L1EventStore) -> None:
        # Store events normally (which writes to FTS)
        for i in range(3):
            await store.store(_make_event(
                event_id=f"evt-{i:03d}",
                content=f"event content {i}",
            ))

        # Clear FTS table manually to simulate pre-existing data
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute("DELETE FROM l1_events_fts")
            await db.commit()

        # Backfill
        count = await store.backfill_fts()
        assert count == 3

        # Verify FTS is populated
        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l1_events_fts") as cursor:
                row = await cursor.fetchone()
        assert row[0] == 3

    async def test_backfill_skips_already_indexed(self, store: L1EventStore) -> None:
        # Store an event (auto-indexed)
        await store.store(_make_event(event_id="evt-001", content="already indexed"))

        # Backfill should skip the already-indexed event
        count = await store.backfill_fts()
        assert count == 0

    async def test_backfill_skips_deleted_events(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-001", content="to be deleted"))
        await store.mark_deleted("evt-001")

        # Clear any remaining FTS entries
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute("DELETE FROM l1_events_fts")
            await db.commit()

        count = await store.backfill_fts()
        assert count == 0  # deleted events should not be backfilled

    async def test_backfill_searchable_after(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-001", content="Python programming tutorial"))

        # Clear FTS, then backfill
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute("DELETE FROM l1_events_fts")
            await db.commit()

        await store.backfill_fts()

        # Should be searchable via BM25
        results = await store.bm25_search("Python", limit=5)
        assert len(results) > 0
        assert results[0][0] == "evt-001"
