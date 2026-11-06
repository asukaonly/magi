"""Cross-domain readers consume owner methods, never physical storage paths."""

import ast
import re
from pathlib import Path

import pytest

from _shared.source_imports import imported_names


def _code_references(source: str) -> set[str]:
    """Inspect symbols, calls and SQL literals without matching documentation."""
    tree = ast.parse(source)
    references = set()
    aliases = {}
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = (
                ("." * node.level + (node.module or "")) if isinstance(node, ast.ImportFrom) else ""
            )
            references.add(module)
            for alias in node.names:
                qualified = f"{module}.{alias.name}" if module else alias.name
                references.update((alias.name, qualified))
                aliases[alias.asname or alias.name] = qualified
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            references.add(node.id)
        elif isinstance(node, ast.Attribute):
            references.update((node.attr, ast.unparse(node)))
        elif isinstance(node, ast.arg):
            references.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            references.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            references.add(node.name)
        elif isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            references.add(aliases.get(name, name) + "(")
            if name in {"getattr", "setattr", "hasattr"} and len(node.args) > 1:
                if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    references.add(node.args[1].value)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            if re.match(
                r"\s*(SELECT|INSERT|DELETE|UPDATE|PRAGMA|VACUUM|CREATE|ALTER|DROP|WITH)\b",
                node.value,
                re.I,
            ):
                references.add(" ".join(node.value.upper().split()))
        annotation = getattr(node, "annotation", None) or getattr(node, "returns", None)
        if annotation is not None:
            references.update(
                item.value
                for item in ast.walk(annotation)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return references


def _references(path: Path) -> set[str]:
    return _code_references(path.read_text(encoding="utf-8-sig"))


def _assert_absent(references: set[str], forbidden: str, path: object = "") -> None:
    assert not any(forbidden in reference for reference in references), (path, forbidden)


@pytest.mark.parametrize(
    "source,forbidden",
    [
        ("import sqlite3 as driver", "sqlite"),
        ("from .storage import repository as owner", ".storage"),
        ("from .index import SqliteVecIndex as Index\nIndex ()", "SqliteVecIndex("),
        ("def query(db_path): pass", "db_path"),
        ('def query() -> "sqlite3.Row": pass', "sqlite"),
        ('getattr(store, "db_path")', "db_path"),
        ('db.execute("select\\n * from events")', "SELECT "),
        ('db.execute(f"DELETE FROM trace_{table}")', "DELETE FROM TRACE_"),
    ],
)
def test_storage_boundary_checker_finds_code_references(source, forbidden):
    with pytest.raises(AssertionError):
        _assert_absent(_code_references(source), forbidden)


def test_storage_boundary_checker_ignores_comments_docstrings_and_prose():
    source = '''"""SELECT * FROM trace_events; sqlite3 db_path SqliteVecIndex()."""
# from .storage import SqliteVecIndex
message = "The sqlite3 driver uses db_path and SELECT statements."
def query():
    """DELETE FROM trace_events; sqlite3 db_path."""
    return repository.list_events()
'''
    references = _code_references(source)
    for forbidden in ("sqlite", "db_path", "SqliteVecIndex(", "SELECT ", "DELETE FROM TRACE_"):
        _assert_absent(references, forbidden)


def test_source_readiness_does_not_depend_on_memory_storage_implementation():
    source = Path(__file__).parents[2] / "src" / "magi" / "awareness" / "source_readiness.py"
    text = _references(source)
    for forbidden in ("sqlite", "db_path", "active_projection_event_predicate", "SELECT "):
        _assert_absent(text, forbidden)


def test_event_query_service_does_not_build_sql_or_decode_driver_rows():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory" / "l1" / "retrieval"
    for name in (
        "common.py",
        "fts.py",
        "search_text.py",
        "../presentation.py",
        "queries.py",
        "idempotency.py",
        "maintenance.py",
        "../source_facets.py",
        "../cognition_handoffs.py",
        "../entities/links.py",
        "../embeddings/events.py",
        "../embeddings/chunks.py",
        "../embeddings/profiles.py",
        "../embeddings/search.py",
        "../embeddings/common.py",
        "../writes.py",
        "../chat_sessions.py",
    ):
        text = _references(root / name)
        for forbidden in ("sqlite", "db_path", "SELECT ", "row_factory"):
            _assert_absent(text, forbidden, (name, forbidden))


def test_timeline_service_and_router_do_not_construct_database_adapters():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in ("timeline/service.py", "api/routers/timeline.py"):
        text = _references(root / name)
        for forbidden in (
            "sqlite",
            "db_path",
            "DailyMoodAggregateStore",
            "SqliteTimelineCoverRepository",
            "SELECT ",
        ):
            _assert_absent(text, forbidden, (name, forbidden))


def test_memory_knowledge_routes_use_owner_ports():
    root = Path(__file__).parents[2] / "src" / "magi" / "api" / "routers" / "memory" / "l2"
    for name in (
        "knowledge_routes.py",
        "review_routes.py",
        "context_routes.py",
        "correction_routes.py",
        "../archive_routes.py",
    ):
        text = _references(root / name)
        for forbidden in (
            "sqlite",
            "db_path",
            "MemoryCorrectionRepository",
            "ContextCatalog(",
            "SELECT ",
        ):
            _assert_absent(text, forbidden, (name, forbidden))


def test_projection_services_do_not_construct_storage_repositories():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in (
        "api/routers/memory/portrait_self_routes.py",
        "user_profile/query_service.py",
        "user_profile/correction_derivation.py",
        "user_profile/portrait_projection_scheduler.py",
        "user_profile/portrait_claim_query.py",
        "user_profile/portrait_projection_builder.py",
        "user_profile/portrait_projection_freshness.py",
        "context/user_profile_service.py",
    ):
        text = _references(root / name)
        for forbidden in (
            "db_path",
            "sqlite",
            "MemoryCorrectionRepository",
            "UserProfileProjectionRepository",
            "UserPortraitProjectionRepository",
        ):
            _assert_absent(text, forbidden, (name, forbidden))


def test_vector_engine_construction_is_centralized():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory"
    for source in root.rglob("*.py"):
        relative = source.relative_to(root).as_posix()
        if relative in {"embedding/sqlite_factory.py", "embedding/sqlite_vec_index.py"}:
            continue
        text = source.read_text(encoding="utf-8-sig")
        if "SqliteVecIndex" in text:
            _assert_absent(_code_references(text), "SqliteVecIndex(", relative)


def test_image_consumers_depend_on_repository_contract():
    root = Path(__file__).parents[2] / "src" / "magi"
    for name in (
        "timeline/service.py",
        "memory/manual_entries/application.py",
        "api/routers/memory/asset_uploads.py",
    ):
        text = _references(root / name)
        assert "ImageAssetRepository" in text
        assert "asset_io" in text
        _assert_absent(text, "ManualEntryAssetStore")
        imports = imported_names(
            (root / name).read_text(), package="magi." + name.rsplit("/", 1)[0].replace("/", ".")
        )
        assert not any(
            imported == "magi.memory.manual_entries.asset_store"
            or imported.startswith("magi.memory.manual_entries.asset_store.")
            for imported in imports
        ), name


def test_event_service_construction_does_not_choose_concrete_storage():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory" / "l1"
    text = _references(root / "event_store.py")
    for forbidden in ("Sqlite", "db_path", "get_magi_home", ".storage."):
        _assert_absent(text, forbidden, forbidden)
    lifecycle = _references(root / "lifecycle.py")
    for forbidden in ("db_path", "SCHEMA_SQL", "executescript", "sqlite_connection"):
        _assert_absent(lifecycle, forbidden, forbidden)


def test_chat_cleanup_does_not_open_or_query_trace_storage():
    source = (
        Path(__file__).parents[2] / "src" / "magi" / "chat" / "storage" / "relational_reader.py"
    )
    text = _references(source)
    for forbidden in (
        "_runtime_trace_db_path",
        "DELETE FROM TRACE_",
        "DELETE FROM AGENT_RUN_",
        "DELETE FROM RUNTIME_NOTIFICATIONS",
    ):
        _assert_absent(text, forbidden, forbidden)
    _assert_absent(text, "TraceContentRepository")
    assert "TraceContentRepository" in _references(source.parents[1] / "service.py")


def test_chat_write_contract_does_not_expose_sqlite_or_paths():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat"
    text = _references(root / "ports.py")
    for forbidden in ("sqlite", "db_path", "Connection", "Row", ".storage"):
        _assert_absent(text, forbidden, forbidden)
    assert not (root / "store.py").exists()
    _assert_absent(_references(root / "task_agent" / "context_assembler.py"), "_chat_db_path")
    _assert_absent(_references(root / "workspace_identity.py"), "SELECT ")


def test_chat_read_contract_has_no_physical_storage_access():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat"
    text = _references(root / "read_ports.py")
    for forbidden in ("sqlite", "db_path", "Connection", "Row", ".storage"):
        _assert_absent(text, forbidden, forbidden)
    assert not (root / "read_service.py").exists()


def test_shared_chat_write_workflows_do_not_open_sqlite_connections():
    storage = Path(__file__).parents[2] / "src" / "magi" / "chat" / "storage"
    for name in (
        "relational_store",
        "sessions",
        "messages",
        "turns",
        "model_context",
        "delivery_outcomes",
        "delivery_failures",
        "user_turn_acceptance",
        "user_turn_delivery_ledger",
        "assistant_memory_outbox",
        "outbound_delivery",
        "post_turn_outbox",
        "task_execution_budgets",
    ):
        source = _references(storage / f"{name}.py")
        _assert_absent(source, "sqlite_connection", name)
        _assert_absent(source, "aiosqlite", name)
        _assert_absent(source, "db_path", name)


def test_shared_chat_reader_delegates_driver_and_physical_cleanup():
    storage = Path(__file__).parents[2] / "src" / "magi" / "chat" / "storage"
    paths = [storage / "relational_reader.py", *(storage / "relational_read").glob("*.py")]
    for path in paths:
        source = _references(path)
        for forbidden in ("sqlite3", "connect_sqlite", "_chat_db_path", "PRAGMA ", "VACUUM"):
            _assert_absent(source, forbidden, (path.name, forbidden))


def test_chat_artifact_and_dependency_consumers_use_owner_ports():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat"
    for name in ("asset_gc.py", "code_delegation_artifacts.py", "conversation_log/log.py"):
        source = _references(root / name)
        for forbidden in ("sqlite", "chat_db_path", "SELECT ", "INSERT "):
            _assert_absent(source, forbidden, (name, forbidden))
    assert not (root / "conversation_log/store.py").exists()


def test_chat_prompt_caches_do_not_open_trace_storage():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat" / "task_agent"
    for name in ("tool_state_view.py", "context_assembler.py"):
        source = _references(root / name)
        for forbidden in ("sqlite", "db_path", "SELECT ", "trace_tools"):
            _assert_absent(source, forbidden, (name, forbidden))


def test_memory_coordinator_does_not_select_hotspot_storage():
    root = Path(__file__).parents[2] / "src" / "magi" / "memory"
    source = _references(root / "unified_store.py")
    for forbidden in (
        "SqliteVectorIndexFactory",
        "SqliteAssetReferenceRepository",
        "DailyMoodAggregateStore",
        "ArchiveReader",
    ):
        _assert_absent(source, forbidden, forbidden)


def test_product_api_does_not_handle_database_drivers():
    root = Path(__file__).parents[2] / "src" / "magi" / "api"
    for path in root.rglob("*.py"):
        source = _references(path)
        for forbidden in ("sqlite3", "aiosqlite", "sqlite3.Error", "aiosqlite.Error"):
            _assert_absent(source, forbidden, (path, forbidden))


def test_read_port_cannot_mutate_sessions_or_deliveries():
    from magi.chat.read_ports import ChatReadRepository

    for method in (
        "create_new_session",
        "rename_session",
        "delete_session",
        "clear_all_sessions",
        "forget_message_artifacts",
        "reset_user_turn_delivery_after_failed_clear",
    ):
        assert not hasattr(ChatReadRepository, method)


def test_chat_persistence_cannot_delete_external_content():
    root = Path(__file__).parents[2] / "src" / "magi" / "chat" / "storage"
    for path in [root / "relational_reader.py", *(root / "relational_read").glob("*.py")]:
        source = _references(path)
        for forbidden in (
            "TraceContentRepository",
            "ChatAssetGC",
            "CodeAgentArtifactGC",
            "_delete_runtime_trace",
            "_delete_chat_message_assets",
            "_clear_all_chat_assets",
        ):
            _assert_absent(source, forbidden, (path.name, forbidden))
