"""Stable context identity and local resolver regression tests."""

from __future__ import annotations

import json
import shutil
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
from magi.memory.context_scope import (
    ContextCatalog,
    ContextResolutionSignals,
    ContextScopeError,
    ContextScopeResolver,
    context_id_for_builtin,
    context_id_for_legacy_value,
    context_id_for_workspace,
    workspace_binding_id,
)
from magi.memory.context_scope.cache_epoch import context_cache_epoch
from magi.memory.l2.corrections.fingerprints import (
    canonical_scope_json,
    scope_key,
    scope_matches,
    scope_specificity,
)
from magi.memory.l2.retrieval.common import matching_scope_keys
from magi.memory.hybrid_retrieval.models import IntentDecision, RetrievalConfig
from magi.memory.hybrid_retrieval.router import build_query
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l2.store import L2CognitionStore
from magi.memory.shared_clear import clear_shared_auxiliary_memory


def _condition(dimension: str, suffix: str) -> dict[str, str]:
    return {
        "dimension": dimension,
        "context_id": f"ctx_{dimension}_{suffix * 64}",
    }


def test_scope_identity_is_order_independent_and_subset_matchable() -> None:
    project = _condition("project", "a")
    activity = _condition("activity", "b")
    claim_scope = {"all_of": [project]}
    context_scope = {"all_of": [activity, project]}

    assert canonical_scope_json(context_scope) == canonical_scope_json(
        {"all_of": [project, activity]}
    )
    assert scope_matches(claim_scope, context_scope) is True
    assert scope_matches(context_scope, claim_scope) is False
    assert scope_specificity(context_scope) == 2
    assert matching_scope_keys(context_scope) == [
        "global",
        scope_key({"all_of": [activity]}),
        scope_key({"all_of": [project]}),
        scope_key(context_scope),
    ]


def test_legacy_free_text_scope_is_rejected_at_runtime() -> None:
    with pytest.raises(ContextScopeError):
        canonical_scope_json({"project": "magi"})
    for invalid in ([], "", 0, False):
        with pytest.raises(ContextScopeError):
            canonical_scope_json(invalid)  # type: ignore[arg-type]


def test_internal_time_identity_remains_readable_but_scoped() -> None:
    time_scope = {"all_of": [_condition("time", "c")]}

    assert canonical_scope_json(time_scope).startswith('{"all_of"')
    assert scope_matches(time_scope, {}) is False
    assert scope_key(time_scope) != "global"


def test_workspace_identity_without_state_treats_a_move_as_a_new_project(
    tmp_path,
) -> None:
    original = tmp_path / "before" / "magi"
    original.mkdir(parents=True)
    before_context_id = context_id_for_workspace(str(original))
    before_binding_id = workspace_binding_id(str(original))
    assert not (original / ".magi").exists()

    moved = tmp_path / "after" / "renamed"
    moved.parent.mkdir(parents=True)
    shutil.move(str(original), str(moved))

    assert context_id_for_workspace(str(moved)) != before_context_id
    assert workspace_binding_id(str(moved)) != before_binding_id
    assert not (moved / ".magi").exists()


def test_workspace_identity_without_state_is_deterministic_and_path_isolated(
    tmp_path,
) -> None:
    first = tmp_path / "first" / "magi"
    second = tmp_path / "second" / "magi"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert context_id_for_workspace(str(first)) == context_id_for_workspace(str(first))
    assert context_id_for_workspace(str(first)) != context_id_for_workspace(str(second))
    assert not (first / ".magi").exists()
    assert not (second / ".magi").exists()


def test_workspace_identity_ignores_an_invalid_persisted_root(tmp_path) -> None:
    workspace = tmp_path / "magi"
    workspace.mkdir()
    paths = WorkspacePaths.from_root(workspace)
    paths.ensure_local_overlay()
    paths.state_path.write_text(
        json.dumps(
            {
                "workspaceId": "repo-main",
                "workspaceRoot": "\u0000invalid-root",
            }
        ),
        encoding="utf-8",
    )

    with_invalid_state = context_id_for_workspace(str(workspace))
    paths.state_path.unlink()

    assert context_id_for_workspace(str(workspace)) == with_invalid_state


@pytest.mark.asyncio
async def test_workspace_registration_prefers_existing_moved_path_label(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    old_path = tmp_path / "OldName"
    old_path.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(old_path)).claim_identity()
    expected_context_id = context_id_for_workspace(str(old_path))
    new_path = tmp_path / "NewName"
    shutil.move(str(old_path), str(new_path))
    WorkspaceStateStore(WorkspacePaths.from_root(new_path)).rebind_identity(old_path)

    options = await ContextCatalog(db_path).sync_workspace_project_options(
        [str(old_path), str(new_path)]
    )

    assert len(options) == 1
    assert options[0].context_id == expected_context_id
    assert options[0].label == "NewName"
    assert (new_path / ".magi").exists()


@pytest.mark.asyncio
async def test_workspace_claim_before_registration_keeps_durable_identity(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "magi"
    workspace.mkdir()
    catalog = ContextCatalog(db_path)

    temporary_context_id = context_id_for_workspace(str(workspace))
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    before = await catalog.register_workspace(str(workspace))
    after = await catalog.register_workspace(str(workspace))

    assert before is not None
    assert after is not None
    assert before.context_id != temporary_context_id
    assert after.context_id == before.context_id
    assert after.binding_id == before.binding_id


def test_workspace_identity_separates_a_live_directory_copy(tmp_path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)

    assert context_id_for_workspace(str(original)) != context_id_for_workspace(str(copied))
    assert not (original / ".magi").exists()
    assert not (copied / ".magi").exists()


def test_workspace_identity_accepts_a_custom_persisted_id_after_explicit_move(
    tmp_path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(original, workspace_id="repo-main")).touch()
    before_context_id = context_id_for_workspace(str(original))
    moved = tmp_path / "moved"

    shutil.move(str(original), str(moved))
    WorkspaceStateStore(WorkspacePaths.from_root(moved)).rebind_identity(original)

    assert context_id_for_workspace(str(moved)) == before_context_id


@pytest.mark.asyncio
async def test_resolver_registers_a_workspace_only_once_per_process(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    resolver = ContextScopeResolver(db_path)
    resolver.catalog.register_workspace = AsyncMock(  # type: ignore[method-assign]
        wraps=resolver.catalog.register_workspace
    )
    signals = ContextResolutionSignals(
        workspace_path=str(workspace),
        user_text="What do I prefer here?",
        task_category="chat",
    )

    first = await resolver.resolve(signals)
    second = await resolver.resolve(signals)
    third = await resolver.resolve(signals)

    assert first == second == third
    assert first["all_of"][0]["dimension"] == "project"
    assert resolver.catalog.register_workspace.await_count == 1


@pytest.mark.asyncio
async def test_unclaimed_workspace_is_not_selectable_or_auto_scoped(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "unclaimed"
    workspace.mkdir()
    catalog = ContextCatalog(db_path)

    options = await catalog.sync_workspace_project_options([str(workspace)])
    resolved = await ContextScopeResolver(db_path).resolve(
        ContextResolutionSignals(workspace_path=str(workspace))
    )

    assert options == []
    assert resolved == {}
    assert not (workspace / ".magi").exists()


@pytest.mark.asyncio
async def test_bound_workspace_wins_over_another_project_name_in_message(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    current_workspace = tmp_path / "current-project"
    mentioned_workspace = tmp_path / "docs"
    current_workspace.mkdir()
    mentioned_workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(current_workspace)).claim_identity()
    WorkspaceStateStore(WorkspacePaths.from_root(mentioned_workspace)).claim_identity()
    catalog = ContextCatalog(db_path)
    await catalog.sync_workspace_project_options([str(current_workspace), str(mentioned_workspace)])

    resolved = await ContextScopeResolver(db_path).resolve(
        ContextResolutionSignals(
            workspace_path=str(current_workspace),
            user_text="Please review the docs folder",
        )
    )

    assert resolved == {
        "all_of": [
            {
                "dimension": "project",
                "context_id": context_id_for_workspace(str(current_workspace)),
            }
        ]
    }


@pytest.mark.asyncio
async def test_resolver_ignores_invalid_workspace_and_keeps_other_context(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    activity_context_id = context_id_for_builtin("activity", "coding")

    resolved = await ContextScopeResolver(db_path).resolve(
        ContextResolutionSignals(
            workspace_path="\0invalid",
            task_category="coding",
        )
    )

    assert resolved == {"all_of": [{"dimension": "activity", "context_id": activity_context_id}]}


@pytest.mark.asyncio
async def test_catalog_epoch_changes_only_when_workspace_options_change(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    catalog = ContextCatalog(db_path)

    await catalog.sync_workspace_project_options([str(workspace)])
    after_first_sync = context_cache_epoch(db_path)
    await catalog.sync_workspace_project_options([str(workspace)])

    assert context_cache_epoch(db_path) == after_first_sync


@pytest.mark.asyncio
async def test_live_resolver_forgets_an_alias_after_catalog_deactivation(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "PrivateProject"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    catalog = ContextCatalog(db_path)
    option = (await catalog.sync_workspace_project_options([str(workspace)]))[0]
    resolver = ContextScopeResolver(db_path)

    assert await resolver.resolve(ContextResolutionSignals(user_text="Open PrivateProject")) == {
        "all_of": [{"dimension": "project", "context_id": option.context_id}]
    }
    await catalog.sync_workspace_project_options([])

    assert await resolver.resolve(ContextResolutionSignals(user_text="Open PrivateProject")) == {}


@pytest.mark.asyncio
async def test_time_aliases_are_not_loaded_into_text_resolution(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    time_context_id = context_id_for_legacy_value("time", "tomorrow")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'time', 'tomorrow', 'legacy_custom', 1, 0, 0)
            """,
            (time_context_id,),
        )
        connection.execute(
            """
            INSERT INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, 'tomorrow', 'tomorrow', 0)
            """,
            (time_context_id,),
        )
        connection.commit()

    aliases = await ContextCatalog(db_path).list_aliases_by_dimension()
    resolved = await ContextScopeResolver(db_path).resolve(
        ContextResolutionSignals(user_text="What happened tomorrow?")
    )

    assert aliases["time"] == []
    assert resolved == {}


@pytest.mark.asyncio
async def test_real_workspace_disambiguates_two_projects_with_the_same_name(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    first_workspace = tmp_path / "first" / "magi"
    second_workspace = tmp_path / "second" / "magi"
    first_workspace.mkdir(parents=True)
    second_workspace.mkdir(parents=True)
    WorkspaceStateStore(WorkspacePaths.from_root(first_workspace)).claim_identity()
    WorkspaceStateStore(WorkspacePaths.from_root(second_workspace)).claim_identity()
    catalog = ContextCatalog(db_path)
    legacy_id = context_id_for_legacy_value("project", "magi")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'project', 'magi', 'legacy_custom', 1, 0, 0)
            """,
            (legacy_id,),
        )
        connection.execute(
            """
            INSERT INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, 'magi', 'magi', 0)
            """,
            (legacy_id,),
        )
        connection.commit()
    first_option = await catalog.register_workspace(str(first_workspace))
    first_legacy_state = await catalog.get_context(legacy_id)
    second_option = await catalog.register_workspace(str(second_workspace))
    assert first_option is not None
    assert second_option is not None
    first_id, second_id = first_option.context_id, second_option.context_id
    assert first_id == context_id_for_workspace(str(first_workspace))
    assert second_id == context_id_for_workspace(str(second_workspace))
    legacy = await catalog.get_context(legacy_id)
    assert legacy is not None
    assert legacy["source_kind"] == "legacy_custom"
    assert legacy["binding_id"] is None
    assert first_legacy_state is not None
    assert first_legacy_state["binding_id"] is None

    reverse_db_path = str(tmp_path / "reverse-memory.db")
    await apply_memory_shared_schema(reverse_db_path)
    reverse_options = await ContextCatalog(reverse_db_path).register_workspaces(
        [str(second_workspace), str(first_workspace)]
    )
    assert [item.context_id for item in reverse_options] == [second_id, first_id]

    resolver = ContextScopeResolver(db_path)
    resolved = await resolver.resolve(
        ContextResolutionSignals(
            workspace_path=str(first_workspace),
            user_text="Magi 项目里之前怎么处理的？",
        )
    )
    ambiguous_without_workspace = await ContextScopeResolver(db_path).resolve(
        ContextResolutionSignals(user_text="Magi 项目里之前怎么处理的？")
    )

    assert resolved == {"all_of": [{"dimension": "project", "context_id": first_id}]}
    assert ambiguous_without_workspace == {}


@pytest.mark.asyncio
async def test_project_options_exclude_unbound_legacy_contexts(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    legacy_id = context_id_for_legacy_value("project", "Unbound")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'project', 'Unbound', 'legacy_custom', 1, 0, 0)
            """,
            (legacy_id,),
        )
        connection.execute(
            """
            INSERT INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, 'unbound', 'Unbound', 0)
            """,
            (legacy_id,),
        )
        connection.commit()

    workspace = tmp_path / "Bound"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    catalog = ContextCatalog(db_path)
    bound = await catalog.register_workspace(str(workspace))

    assert bound is not None
    assert [item.context_id for item in await catalog.list_workspace_project_options()] == [
        bound.context_id
    ]


@pytest.mark.asyncio
async def test_context_labels_hide_internal_ids(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    context_id = f"ctx_project_{'f' * 64}"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'project', ?, 'legacy_custom', 1, 0, 0)
            """,
            (context_id, context_id),
        )
        connection.commit()

    assert await ContextCatalog(db_path).get_context_labels({context_id}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("clear_path", ["l2", "shared"])
async def test_clear_removes_user_contexts_and_invalidates_a_live_resolver(
    tmp_path,
    clear_path: str,
) -> None:
    db_path = str(tmp_path / f"{clear_path}.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / clear_path / "PrivateProject"
    workspace.mkdir(parents=True)
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    catalog = ContextCatalog(db_path)
    workspace_context = await catalog.register_workspace(str(workspace))
    assert workspace_context is not None
    place_context_id = context_id_for_legacy_value("place", "SecretPlace")
    coding_context_id = context_id_for_builtin("activity", "coding")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 0, 0)
            """,
            (place_context_id, "place", "SecretPlace", "legacy_custom"),
        )
        connection.execute(
            """
            INSERT INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, ?, ?, 0)
            """,
            (place_context_id, "secretplace", "SecretPlace"),
        )
        connection.commit()

    resolver = ContextScopeResolver(db_path)
    assert await resolver.resolve(ContextResolutionSignals(user_text="Meet at SecretPlace")) == {
        "all_of": [{"dimension": "place", "context_id": place_context_id}]
    }
    assert await resolver.resolve(ContextResolutionSignals(workspace_path=str(workspace))) == {
        "all_of": [{"dimension": "project", "context_id": workspace_context.context_id}]
    }

    if clear_path == "l2":
        await L2CognitionStore(db_path=db_path).clear()
    else:
        await clear_shared_auxiliary_memory(db_path)

    with sqlite3.connect(db_path) as connection:
        remaining = connection.execute(
            "SELECT context_id, source_kind FROM memory_context_catalog"
        ).fetchall()
        assert remaining == [(coding_context_id, "built_in")]
        assert connection.execute("SELECT COUNT(*) FROM memory_context_bindings").fetchone() == (0,)

    assert await resolver.resolve(ContextResolutionSignals(user_text="Meet at SecretPlace")) == {}
    assert await resolver.resolve(ContextResolutionSignals(task_category="coding")) == {
        "all_of": [{"dimension": "activity", "context_id": coding_context_id}]
    }
    await resolver.resolve(ContextResolutionSignals(workspace_path=str(workspace)))
    assert await catalog.get_context(workspace_context.context_id) is not None


@pytest.mark.asyncio
async def test_correction_scope_requires_a_bound_project(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    catalog = ContextCatalog(db_path)
    unknown_scope = {
        "all_of": [
            {
                "dimension": "project",
                "context_id": f"ctx_project_{'d' * 64}",
            }
        ]
    }

    with pytest.raises(ContextScopeError) as exc_info:
        await catalog.validate_correction_scope(unknown_scope)

    assert exc_info.value.code == "context_scope_unknown"


@pytest.mark.asyncio
async def test_hybrid_retrieval_resolves_every_caller_at_the_shared_entry(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    memory = SimpleNamespace(
        memory_db_path=db_path,
        l0=None,
        l1=None,
        l2=None,
        l3=None,
        l4=None,
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(
            intent_decider_llm_enabled=False,
            grounding_filter_enabled=False,
            query_expansion_enabled=False,
            manifest_selector_enabled=False,
        ),
    )
    service._intent_decider.decide = AsyncMock(  # type: ignore[method-assign]
        return_value=IntentDecision(source="rule_fallback")
    )
    signals = {
        "workspace_path": str(workspace),
        "user_text": "What did we decide here?",
        "task_category": "chat",
    }

    tool_payload = await service.query(build_query(query="decision", context_signals=signals))
    implicit_payload = await service.query(build_query(query="decision", context_signals=signals))

    assert tool_payload.trace["context_scope"] == implicit_payload.trace["context_scope"]
    assert tool_payload.trace["context_scope"]["all_of"][0]["dimension"] == "project"
    first_intent_input = service._intent_decider.decide.await_args_list[0].args[0]
    assert first_intent_input.context_scope == tool_payload.trace["context_scope"]


@pytest.mark.asyncio
async def test_hybrid_retrieval_falls_back_when_automatic_context_resolution_fails(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    memory = SimpleNamespace(
        memory_db_path=db_path,
        l0=None,
        l1=None,
        l2=None,
        l3=None,
        l4=None,
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(
            intent_decider_llm_enabled=False,
            grounding_filter_enabled=False,
            query_expansion_enabled=False,
            manifest_selector_enabled=False,
        ),
    )
    assert service._context_scope_resolver is not None
    service._context_scope_resolver.resolve = AsyncMock(  # type: ignore[method-assign]
        side_effect=sqlite3.OperationalError("catalog unavailable")
    )
    service._intent_decider.decide = AsyncMock(  # type: ignore[method-assign]
        return_value=IntentDecision(source="rule_fallback")
    )

    payload = await service.query(
        build_query(
            query="decision",
            context_signals={"workspace_path": "/unavailable"},
        )
    )

    assert payload.trace["context_scope"] == {}
    with pytest.raises(ContextScopeError):
        await service.query(
            build_query(
                query="decision",
                context_scope={"project": "legacy-free-text"},
            )
        )


def test_build_query_rejects_malformed_context_signals() -> None:
    with pytest.raises(ContextScopeError, match="signals must be an object"):
        build_query(query="decision", context_signals=["not", "an", "object"])
