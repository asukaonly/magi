"""Cross-domain readers consume owner methods, never physical storage paths."""
from pathlib import Path


def test_source_readiness_does_not_depend_on_memory_storage_implementation():
    source = Path(__file__).parents[2] / "src" / "magi" / "awareness" / "source_readiness.py"
    text = source.read_text()
    for forbidden in ("sqlite", "db_path", "active_projection_event_predicate", "SELECT "):
        assert forbidden not in text


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
    ):
        text = (root / name).read_text()
        for forbidden in ("db_path", "sqlite", "MemoryCorrectionRepository", "UserProfileProjectionRepository", "UserPortraitProjectionRepository"):
            assert forbidden not in text, (name, forbidden)
