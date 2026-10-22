"""Cross-domain readers consume owner methods, never physical storage paths."""
from pathlib import Path


def test_source_readiness_does_not_depend_on_memory_storage_implementation():
    source = Path(__file__).parents[2] / "src" / "magi" / "awareness" / "source_readiness.py"
    text = source.read_text()
    for forbidden in ("sqlite", "db_path", "active_projection_event_predicate", "SELECT "):
        assert forbidden not in text


def test_event_query_service_does_not_build_sql_or_decode_driver_rows():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory" / "l1" / "retrieval"
    for name in ("common.py", "fts.py", "search_text.py", "../presentation.py", "queries.py", "idempotency.py", "maintenance.py", "../source_facets.py", "../cognition_handoffs.py", "../entities/links.py", "../embeddings/events.py", "../embeddings/chunks.py", "../embeddings/profiles.py", "../embeddings/search.py", "../embeddings/common.py", "../writes.py", "../chat_sessions.py"):
        text = (root / name).read_text()
        for forbidden in ("sqlite", "db_path", "SELECT ", "row_factory"):
            assert forbidden not in text, (name, forbidden)


def test_timeline_service_and_router_do_not_construct_database_adapters():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in ("timeline/service.py", "api/routers/timeline.py"):
        text = (root / name).read_text()
        for forbidden in ("sqlite", "db_path", "DailyMoodAggregateStore", "SqliteTimelineCoverRepository", "SELECT "):
            assert forbidden not in text, (name, forbidden)


def test_memory_knowledge_routes_use_owner_ports():
    root = Path(__file__).parents[2] / "src" / "magi" / "api" / "routers" / "memory" / "l2"
    for name in ("knowledge_routes.py", "review_routes.py", "context_routes.py", "correction_routes.py", "../archive_routes.py"):
        text = (root / name).read_text()
        for forbidden in ("sqlite", "db_path", "MemoryCorrectionRepository", "ContextCatalog(", "SELECT "):
            assert forbidden not in text, (name, forbidden)


def test_projection_services_do_not_construct_storage_repositories():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in (
        "api/routers/memory/portrait_self_routes.py", "user_profile/query_service.py",
        "user_profile/correction_derivation.py", "user_profile/portrait_projection_scheduler.py",
        "user_profile/portrait_claim_query.py", "user_profile/portrait_projection_builder.py",
        "user_profile/portrait_projection_freshness.py",
        "context/user_profile_service.py",
    ):
        text = (root / name).read_text()
        for forbidden in ("db_path", "sqlite", "MemoryCorrectionRepository", "UserProfileProjectionRepository", "UserPortraitProjectionRepository"):
            assert forbidden not in text, (name, forbidden)


def test_vector_engine_construction_is_centralized():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory"
    for source in root.rglob("*.py"):
        relative = source.relative_to(root).as_posix()
        if relative in {"embedding/sqlite_factory.py", "embedding/sqlite_vec_index.py"}:
            continue
        assert "SqliteVecIndex(" not in source.read_text(), relative


def test_image_consumers_depend_on_repository_contract():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in ("timeline/service.py", "memory/manual_entries/application.py", "api/routers/memory/asset_uploads.py"):
        text = (root / name).read_text()
        assert "ImageAssetRepository" in text
        assert "asset_io" in text
        assert "ManualEntryAssetStore" not in text
        assert "asset_store import" not in text


def test_event_service_construction_does_not_choose_concrete_storage():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory" / "l1"
    text = (root / "event_store.py").read_text()
    for forbidden in ("Sqlite", "db_path", "get_magi_home", ".storage."):
        assert forbidden not in text, forbidden
    lifecycle = (root / "lifecycle.py").read_text()
    for forbidden in ("db_path", "SCHEMA_SQL", "executescript", "sqlite_connection"):
        assert forbidden not in lifecycle, forbidden


def test_chat_cleanup_does_not_open_or_query_trace_storage():
    source = Path(__file__).parents[2] / "src" / "magi" / "chat" / "read_service.py"
    text = source.read_text()
    for forbidden in ("_runtime_trace_db_path", "DELETE FROM trace_", "DELETE FROM agent_run_", "DELETE FROM runtime_notifications"):
        assert forbidden not in text, forbidden
    assert "TraceContentRepository" in text


def test_chat_write_contract_does_not_expose_sqlite_or_paths():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat"
    text = (root / "ports.py").read_text()
    for forbidden in ("sqlite", "db_path", "Connection", "Row", ".storage"):
        assert forbidden not in text, forbidden
    assert not (root / "store.py").exists()
    assert "_chat_db_path" not in (root / "task_agent" / "context_assembler.py").read_text()
    assert "SELECT " not in (root / "workspace_identity.py").read_text()
