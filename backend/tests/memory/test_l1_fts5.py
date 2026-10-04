"""Tests for FTS5 index integration with L1EventStore and fts_utils."""

from __future__ import annotations

import time

import aiosqlite
import pytest

from magi.memory.hybrid_retrieval.fts_utils import (
    _stem_english_token,
    build_exact_fts_query,
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
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("机器学习性能优化方案讨论", "机器 学习 性能 优化 方案 讨论"),
            ("The quick brown fox jumps", "The quick brown fox jumps"),
            ("我在学习Python编程", "我 在 学习 Python 编程"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_tokenization_preserves_searchable_words(self, text, expected):
        assert tokenize_for_fts(text) == expected


class TestEscapeFtsQuery:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("hello*world", "hello world"),
            ('"exact phrase"', "exact phrase"),
            ("(hello OR world)", "hello OR world"),
            ("hello world", "hello world"),
            ("", ""),
            ("***", ""),
            ("hello   +  world", "hello world"),
        ],
    )
    def test_operators_are_removed_without_losing_words(self, text, expected):
        assert escape_fts_query(text) == expected


class TestStemEnglishToken:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("graduated", "graduat"),
            ("running", "run"),
            ("books", "book"),
            ("studies", "study"),
            ("watches", "watch"),
            ("stopped", "stop"),
            ("swimming", "swim"),
            ("the", "the"),
            ("go", "go"),
            ("degree", "degree"),
            ("making", "mak"),
            ("learning", "learn"),
        ],
    )
    def test_english_stems_preserve_short_and_unsuffixed_words(self, token, expected):
        assert _stem_english_token(token) == expected


@pytest.mark.parametrize(
    "builder,separator", [(build_stemmed_fts_query, " "), (build_or_fts_query, " OR ")]
)
@pytest.mark.parametrize(
    "text,terms",
    [
        ("What degree did I graduate with", ["degre*", "graduat*"]),
        ("the a an", []),
        ("run fast", ["run", "fast"]),
        ("machine learning optimization", ["machin*", "learn*", "optimizatio*"]),
        ("机器 学习", ["机器", "学习"]),
    ],
)
def test_expanded_query_retains_exact_terms_and_boolean_syntax(builder, separator, text, terms):
    assert builder(text) == separator.join(terms)


class TestBuildExactFtsQuery:
    def test_removes_stop_words(self) -> None:
        result = build_exact_fts_query("The Crown")
        assert "the" not in result.split()
        assert result == "crown"

    def test_multiple_tokens(self) -> None:
        result = build_exact_fts_query("Game of Thrones")
        assert result == "game thrones"

    @pytest.mark.parametrize(
        "input_text,expected_query",
        [
            pytest.param("run fast", "run fast", id="preserves_short_tokens"),
            pytest.param("the a an", "", id="empty_after_stop_words"),
        ],
    )
    def test_exact_fts_query_handles_short_tokens_and_stop_words(
        self, input_text, expected_query
    ) -> None:
        result = build_exact_fts_query(input_text)
        assert result == expected_query

    def test_long_tokens_not_truncated(self) -> None:
        result = build_exact_fts_query("graduate programming")
        assert result == "graduate programming"

    def test_cjk_tokens_unchanged(self) -> None:
        result = build_exact_fts_query("机器 学习")
        assert result == "机器 学习"


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
class TestFts5WriteSync:
    async def test_stored_events_are_tokenized_and_independently_searchable(self, store):
        await store.store(_make_event(event_id="chinese", content="机器学习性能优化方案讨论"))
        await store.store(_make_event(event_id="english", content="Python programming tutorial"))
        async with aiosqlite.connect(store.db_path) as db:
            rows = await (
                await db.execute("SELECT event_id, content FROM l1_events_fts ORDER BY event_id")
            ).fetchall()
        assert rows == [
            ("chinese", "机器 学习 性能 优化 方案 讨论 external text"),
            ("english", "Python programming tutorial external text"),
        ]
        assert [row[0] for row in await store.bm25_search("机器学习", strict=True)] == ["chinese"]
        assert [row[0] for row in await store.bm25_search("Python", strict=True)] == ["english"]

    async def test_duplicate_event_id_preserves_original_source_and_index(self, store):
        await store.store(_make_event(event_id="changed", content="original content"))
        await store.store(_make_event(event_id="survivor", content="separate record"))
        assert [row[0] for row in await store.bm25_search("original", strict=True)] == ["changed"]
        await store.store(_make_event(event_id="changed", content="updated content"))
        async with aiosqlite.connect(store.db_path) as db:
            rows = await (
                await db.execute("SELECT event_id, content FROM l1_events_fts ORDER BY event_id")
            ).fetchall()
        assert rows == [
            ("changed", "original content external text"),
            ("survivor", "separate record external text"),
        ]
        assert [row[0] for row in await store.bm25_search("original", strict=True)] == ["changed"]
        assert await store.bm25_search("updated", strict=True) == []
        async with aiosqlite.connect(store.db_path) as db:
            original = await (
                await db.execute("SELECT content FROM fact_events WHERE event_id = ?", ("changed",))
            ).fetchone()
        assert original == ("original content",)
        assert [row[0] for row in await store.bm25_search("separate", strict=True)] == ["survivor"]


@pytest.mark.asyncio
class TestFts5DeleteSync:
    @pytest.mark.parametrize("clear_all", [False, True], ids=["single-delete", "clear"])
    async def test_deletion_removes_previously_searchable_rows(self, store, clear_all):
        for event_id in ("removed", "survivor"):
            await store.store(_make_event(event_id=event_id, content="common keyword"))
        assert {row[0] for row in await store.bm25_search("common keyword")} == {
            "removed",
            "survivor",
        }
        if clear_all:
            await store.clear()
        else:
            await store.mark_deleted("removed")
        expected = [] if clear_all else [("survivor",)]
        async with aiosqlite.connect(store.db_path) as db:
            rows = await (await db.execute("SELECT event_id FROM l1_events_fts")).fetchall()
        assert rows == expected
        assert [row[0] for row in await store.bm25_search("common keyword")] == [
            row[0] for row in expected
        ]


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

    @pytest.mark.parametrize(
        "query_text",
        [
            pytest.param("Python?", id="bm25_search_ignores_question_mark_syntax"),
            pytest.param("Python'", id="bm25_search_ignores_single_quote_syntax"),
        ],
    )
    async def test_bm25_search_ignores_punctuation_syntax(
        self, store: L1EventStore, query_text
    ) -> None:
        await store.store(_make_event(event_id="evt-py", content="Python programming tutorial"))
        results = await store.bm25_search(query_text, limit=10)
        assert len(results) > 0
        assert results[0][0] == "evt-py"

    async def test_bm25_search_ignores_comparison_query_punctuation(
        self, store: L1EventStore
    ) -> None:
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

    async def test_bm25_ranks_repeated_query_terms_ahead_of_sparse_matches(self, store):
        await store.store(_make_event(event_id="dense", content="machine machine machine machine"))
        await store.store(_make_event(event_id="sparse", content="machine learning deep networks"))
        await store.store(_make_event(event_id="unrelated", content="hiking outdoors local parks"))
        results = await store.bm25_search("machine", strict=True)
        assert [row[0] for row in results] == ["dense", "sparse"]
        assert all(isinstance(score, float) for _, score in results)
        assert results[0][1] < results[1][1] < 0

    @pytest.mark.parametrize("limit", [1, 3, 10])
    async def test_bm25_returns_exactly_the_available_limit(self, store, limit):
        expected_ids = {f"evt-{i:03d}" for i in range(10)}
        for event_id in sorted(expected_ids):
            await store.store(
                _make_event(event_id=event_id, content="common keyword shared content")
            )
        assert {
            row[0] for row in await store.bm25_search("common keyword", limit=20)
        } == expected_ids
        results = await store.bm25_search("common keyword", limit=limit)
        ids = [row[0] for row in results]
        assert len(ids) == limit
        assert len(set(ids)) == limit
        assert set(ids) <= expected_ids


@pytest.mark.asyncio
class TestBm25SearchStrict:
    """Tests for strict=True mode which uses exact tokens and skips OR fallback."""

    @pytest.mark.parametrize(
        "strict,expected",
        [
            (True, {"evt-crown"}),
            (False, {"evt-crown", "evt-crowd", "evt-crowded"}),
        ],
    )
    async def test_exact_mode_excludes_prefix_noise(self, store, strict, expected):
        await store.store(
            _make_event(event_id="evt-crown", content="I watched The Crown last night")
        )
        await store.store(
            _make_event(event_id="evt-crowd", content="The crowd was enormous at the show")
        )
        await store.store(
            _make_event(event_id="evt-crowded", content="The subway was very crowded today")
        )
        results = await store.bm25_search("The Crown", limit=10, strict=strict)
        assert {row[0] for row in results} == expected

    async def test_strict_falls_back_to_stemmed(self, store: L1EventStore) -> None:
        """If exact tokens match nothing, strict mode still tries stemmed AND."""
        await store.store(
            _make_event(event_id="evt-grad", content="She graduated with honors last year")
        )

        # "graduate" exact won't match "graduated", but stemmed "graduat*" will
        results = await store.bm25_search("graduate honors", limit=10, strict=True)
        event_ids = [r[0] for r in results]
        assert "evt-grad" in event_ids

    async def test_strict_skips_or_fallback(self, store: L1EventStore) -> None:
        """strict=True should not use OR fallback, so partial matches are excluded."""
        await store.store(
            _make_event(event_id="evt-a", content="I love playing volleyball at the park")
        )
        await store.store(_make_event(event_id="evt-b", content="The charity run was really fun"))

        # In non-strict mode, OR fallback would match both events.
        # In strict mode, AND requires both terms → neither matches both.
        results_strict = await store.bm25_search("volleyball charity", limit=10, strict=True)
        results_normal = await store.bm25_search("volleyball charity", limit=10, strict=False)
        # Strict AND: neither event has both terms
        assert len(results_strict) == 0
        # Normal mode falls to OR: both events match
        assert {row[0] for row in results_normal} == {"evt-a", "evt-b"}


@pytest.mark.asyncio
class TestBackfillFts:
    async def test_backfill_repairs_only_missing_live_events_without_duplicates(self, store):
        contents = {
            "indexed": "Python tutorial",
            "missing-a": "machine learning",
            "missing-b": "quantum physics",
            "deleted": "giraffe habitat",
        }
        for event_id, content in contents.items():
            await store.store(_make_event(event_id=event_id, content=content))
        await store.mark_deleted("deleted")
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute("DELETE FROM l1_events_fts WHERE event_id != 'indexed'")
            await db.commit()
        assert await store.bm25_search("machine", strict=True) == []
        assert await store.bm25_search("quantum", strict=True) == []
        assert [row[0] for row in await store.bm25_search("Python", strict=True)] == ["indexed"]
        assert await store.backfill_fts(batch_size=1) == 2
        for query, expected in (
            ("Python", ["indexed"]),
            ("machine", ["missing-a"]),
            ("quantum", ["missing-b"]),
            ("giraffe", []),
        ):
            assert [row[0] for row in await store.bm25_search(query, strict=True)] == expected
        async with aiosqlite.connect(store.db_path) as db:
            rows = await (
                await db.execute(
                    "SELECT event_id, COUNT(*) FROM l1_events_fts GROUP BY event_id ORDER BY event_id"
                )
            ).fetchall()
        assert rows == [("indexed", 1), ("missing-a", 1), ("missing-b", 1)]
        assert await store.backfill_fts(batch_size=1) == 0
        async with aiosqlite.connect(store.db_path) as db:
            after = await (
                await db.execute(
                    "SELECT event_id, COUNT(*) FROM l1_events_fts GROUP BY event_id ORDER BY event_id"
                )
            ).fetchall()
        assert after == rows
