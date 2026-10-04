"""Tests for UserProfileService backed by L2 stores."""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from magi.context.user_profile_service import UserProfileService
from magi.user_profile.models import PORTRAIT_PROMPT_CONTRACT_VERSION, UserPortraitProjection


class _FakeL2EntityCatalog:
    def __init__(self):
        self.call_count = 0

    async def list_entities(self, entity_ids=None, **kwargs):
        self.call_count += 1
        if entity_ids and entity_ids[0] == "user:alice":
            return [{"entity_id": "user:alice", "canonical_name": "Alice", "aliases": ["ali"]}]
        if entity_ids and entity_ids[0] == "user:hakimi":
            return [{"entity_id": "user:hakimi", "canonical_name": "Asuka", "aliases": ["hakimi"]}]
        return []


class _FakeL2Store:
    def __init__(self):
        self.call_count = 0
        self.assertion_call_count = 0

    async def get_tom_snapshot(self, entity_id=None, entity_type=None):
        self.call_count += 1
        if entity_id == "user:alice":
            return {"preferences": {"language": "zh-CN", "theme": "dark"}}
        if entity_id == "user:hakimi":
            return {
                "preferences": {
                    "address.preferred": '["哈基米", "hakimi"]',
                    "address.disallowed": '["老师", "asuka-sama"]',
                    "address.real_name": "明日香",
                }
            }
        return None

    async def list_current_assertions(self, entity_id=None, entity_type=None, **kwargs):
        self.assertion_call_count += 1
        if entity_id == "user:portrait":
            return [
                {
                    "assertion_id": "a-magi",
                    "entity_id": "user:portrait",
                    "entity_type": "user",
                    "trait_family": "interest_profile",
                    "trait_name": "interest.magi",
                    "trait_value": "Magi 记忆系统",
                    "natural_summary": "用户关注 Magi 记忆系统。",
                    "source_domain": "conversation",
                    "validation_state": "stable",
                    "temporal_scope": "stable",
                    "confidence_score": 0.9,
                    "evidence_events": ["event-1", "event-2"],
                }
            ]
        if entity_id == "user:pending":
            return [
                {
                    "trait_family": "preference_profile",
                    "trait_name": "preference.address.preferred",
                    "trait_value": "哈基米",
                    "validation_state": "tentative",
                }
            ]
        return []


class _RevisionedL2Store(_FakeL2Store):
    def __init__(self):
        super().__init__()
        self.revision = 0

    async def current_subject_revision(self, subject_key: str) -> int:
        assert subject_key.startswith("user:")
        return self.revision


class _FakeUnifiedMemory:
    def __init__(self):
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l2 = _FakeL2Store()


class _BrokenCatalog:
    async def list_entities(self, **kwargs):
        raise RuntimeError("db error")


class _BrokenL2:
    async def get_tom_snapshot(self, **kwargs):
        raise RuntimeError("db error")


class _BrokenUnifiedMemory:
    def __init__(self):
        self.l2_entity_catalog = _BrokenCatalog()
        self.l2 = _BrokenL2()


class TestUserProfileService(unittest.IsolatedAsyncioTestCase):
    async def test_get_display_name_returns_canonical_name(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("alice")
        self.assertEqual(name, "Alice")

    async def _assert_get_display_name_returns_unknown_without_entity(self, user_id_value):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name(user_id_value)
        self.assertEqual(name, "unknown")

    async def test_get_display_name_returns_unknown_for_missing_entity(self):
        await self._assert_get_display_name_returns_unknown_without_entity("nobody")

    async def test_get_display_name_returns_unknown_for_empty_user_id(self):
        await self._assert_get_display_name_returns_unknown_without_entity("")

    async def test_get_display_name_falls_back_to_tentative_assertion_preferences(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("pending")
        self.assertEqual(name, "哈基米")

    async def test_get_display_name_prefers_address_preference_over_canonical_name(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("hakimi")
        self.assertEqual(name, "哈基米")

    async def test_display_name_dependency_fallbacks_preserve_healthy_control(self):
        no_catalog = _FakeUnifiedMemory()
        no_catalog.l2_entity_catalog = None
        for memory, expected in [
            (None, "unknown"),
            (no_catalog, "unknown"),
            (_BrokenUnifiedMemory(), "unknown"),
            (_FakeUnifiedMemory(), "Alice"),
        ]:
            with self.subTest(memory=memory):
                self.assertEqual(
                    await UserProfileService(unified_memory=memory).get_display_name("alice"), expected
                )


    async def test_get_portrait_prompt_summary_builds_clean_projection_when_missing(self):
        with TemporaryDirectory() as tmpdir:
            um = _FakeUnifiedMemory()
            um.l2.db_path = f"{tmpdir}/memory.db"
            svc = UserProfileService(unified_memory=um)

            summary = await svc.get_portrait_prompt_summary("portrait")

        rendered = "\n".join(summary)
        self.assertIn("Magi 记忆系统", rendered)
        self.assertNotIn("interest.", rendered)
        self.assertNotIn("affinity", rendered)

    async def test_get_preference_summary_normalizes_addressing_values(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("hakimi")
        self.assertEqual(
            prefs,
            {
                "address.preferred": ["哈基米", "hakimi"],
                "address.disallowed": ["老师", "asuka-sama"],
                "address.real_name": "明日香",
            },
        )

    async def test_preference_fallbacks_preserve_healthy_control(self):
        no_l2 = _FakeUnifiedMemory()
        no_l2.l2 = None
        for memory, user, expected in [
            (None, "alice", {}),
            (no_l2, "alice", {}),
            (_BrokenUnifiedMemory(), "alice", {}),
            (_FakeUnifiedMemory(), "nobody", {}),
            (_FakeUnifiedMemory(), "alice", {"language": "zh-CN", "theme": "dark"}),
        ]:
            with self.subTest(memory=memory, user=user):
                self.assertEqual(
                    await UserProfileService(unified_memory=memory).get_preference_summary(user),
                    expected,
                )

    async def test_get_preference_summary_falls_back_to_tentative_assertions(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("pending")
        self.assertEqual(prefs, {"address.preferred": "哈基米"})


    # -- Cache behaviour ---------------------------------------------------

    async def test_repeated_calls_use_cache(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um)

        await svc.get_display_name("alice")
        await svc.get_display_name("alice")
        await svc.get_preference_summary("alice")

        # Only one DB round-trip for each store.
        self.assertEqual(um.l2_entity_catalog.call_count, 1)
        self.assertEqual(um.l2.call_count, 1)

    async def test_durable_subject_revision_invalidates_cache_before_ttl(self):
        um = _FakeUnifiedMemory()
        um.l2 = _RevisionedL2Store()
        svc = UserProfileService(unified_memory=um, cache_ttl=300)

        await svc.get_display_name("alice")
        await svc.get_display_name("alice")
        self.assertEqual(um.l2_entity_catalog.call_count, 1)

        um.l2.revision += 1
        await svc.get_display_name("alice")

        self.assertEqual(um.l2_entity_catalog.call_count, 2)

    async def test_revision_failure_bounds_refreshed_cache_and_recovery_to_current_source(self):
        memory = _FakeUnifiedMemory()
        memory.l2 = _RevisionedL2Store()
        clock = [100.0]
        service = UserProfileService(unified_memory=memory, cache_ttl=300)
        name = ["Healthy"]
        memory.l2_entity_catalog.list_entities = AsyncMock(
            side_effect=lambda **kwargs: [{"entity_id": "user:alice", "canonical_name": name[0]}]
        )
        with patch(
            "magi.context.user_profile_service.time", SimpleNamespace(monotonic=lambda: clock[0])
        ):
            self.assertEqual(await service.get_display_name("alice"), "Healthy")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 1)
            memory.l2.current_subject_revision = AsyncMock(
                side_effect=RuntimeError("revision unavailable")
            )
            name[0] = "Refreshed during outage"
            clock[0] = 101.0
            self.assertEqual(await service.get_display_name("alice"), "Refreshed during outage")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 2)
            name[0] = "Changed during outage"
            clock[0] = 105.9
            self.assertEqual(await service.get_display_name("alice"), "Refreshed during outage")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 2)
            clock[0] = 106.0
            self.assertEqual(await service.get_display_name("alice"), "Changed during outage")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 3)
            memory.l2.current_subject_revision = AsyncMock(return_value=1)
            name[0] = "Recovered"
            clock[0] = 107.0
            self.assertEqual(await service.get_display_name("alice"), "Recovered")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 4)
            clock[0] = 113.0
            self.assertEqual(await service.get_display_name("alice"), "Recovered")
            self.assertEqual(memory.l2_entity_catalog.list_entities.await_count, 4)

    async def test_cache_returns_independent_dict_copy(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs1 = await svc.get_preference_summary("alice")
        prefs1["mutated"] = True
        prefs2 = await svc.get_preference_summary("alice")
        self.assertNotIn("mutated", prefs2)

    async def test_invalidation_refreshes_only_its_requested_scope(self):
        for scope in ["alice", None]:
            with self.subTest(scope=scope):
                memory = _FakeUnifiedMemory()
                names = {"user:alice": "Alice", "user:bob": "Bob"}

                async def catalog(*, entity_ids, **kwargs):
                    key = entity_ids[0]
                    return [{"entity_id": key, "canonical_name": names[key]}]

                memory.l2_entity_catalog.list_entities = AsyncMock(side_effect=catalog)
                service = UserProfileService(unified_memory=memory)
                self.assertEqual(
                    [await service.get_display_name(user) for user in ["alice", "bob"]],
                    ["Alice", "Bob"],
                )
                names.update({"user:alice": "Alice changed", "user:bob": "Bob changed"})
                service.invalidate(scope)
                self.assertEqual(
                    [await service.get_display_name(user) for user in ["alice", "bob"]],
                    ["Alice changed", "Bob changed" if scope is None else "Bob"],
                )
                self.assertEqual(
                    [
                        call.kwargs["entity_ids"]
                        for call in memory.l2_entity_catalog.list_entities.await_args_list
                    ],
                    [["user:alice"], ["user:bob"], ["user:alice"]]
                    + ([["user:bob"]] if scope is None else []),
                )


    async def test_profile_cache_reuses_until_finite_ttl_and_then_refreshes(self):
        memory = _FakeUnifiedMemory()
        clock = [100.0]
        service = UserProfileService(unified_memory=memory, cache_ttl=10)
        with patch(
            "magi.context.user_profile_service.time", SimpleNamespace(monotonic=lambda: clock[0])
        ):
            self.assertEqual(await service.get_display_name("alice"), "Alice")
            clock[0] = 109.9
            self.assertEqual(await service.get_display_name("alice"), "Alice")
            self.assertEqual(memory.l2_entity_catalog.call_count, 1)
            clock[0] = 110.0
            self.assertEqual(await service.get_display_name("alice"), "Alice")
            self.assertEqual(memory.l2_entity_catalog.call_count, 2)
            self.assertEqual(memory.l2.call_count, 2)

    async def test_empty_cache_uses_shorter_ttl(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um, cache_ttl=300, empty_cache_ttl=0)

        await svc.get_display_name("nobody")
        await svc.get_display_name("nobody")

        self.assertEqual(um.l2_entity_catalog.call_count, 2)


if __name__ == "__main__":
    unittest.main()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_l2", "profile", "freshness", "rebuild"])
@pytest.mark.parametrize("contract_version", [0, PORTRAIT_PROMPT_CONTRACT_VERSION, PORTRAIT_PROMPT_CONTRACT_VERSION + 1])
async def test_portrait_prompt_failure_fallback_requires_current_semantic_contract(failure, contract_version):
    old_text = "用户关注或偏好：这条记录缺少完整事实描述。"
    current_text = "用户希望被称为小林。"
    line = current_text if contract_version == PORTRAIT_PROMPT_CONTRACT_VERSION else old_text
    cached = UserPortraitProjection(
        user_id="audit", world={}, review={}, recent={},
        prompt_summary=[line], prompt_contract_version=contract_version,
    )
    repo = SimpleNamespace(get=AsyncMock(return_value=cached), upsert=AsyncMock())
    service = UserProfileService(unified_memory=SimpleNamespace(l2=None if failure == "missing_l2" else object()))
    profile = AsyncMock(side_effect=RuntimeError("profile unavailable")) if failure == "profile" else AsyncMock(return_value=None)
    freshness = AsyncMock(side_effect=RuntimeError("freshness unavailable")) if failure == "freshness" else AsyncMock(return_value=True)
    builder = SimpleNamespace(build=AsyncMock(side_effect=RuntimeError("rebuild unavailable")))
    with patch.object(service, "_memory_db_path", return_value="/unused-audit-memory.db"), patch.object(service, "_current_profile_projection", profile), patch("magi.context.user_profile_service.UserPortraitProjectionRepository", return_value=repo), patch("magi.context.user_profile_service.portrait_projection_is_stale", freshness), patch("magi.context.user_profile_service.UserPortraitProjectionBuilder", return_value=builder):
        actual = await service._fetch_portrait_prompt_summary("audit")
    assert actual == ([current_text] if contract_version == PORTRAIT_PROMPT_CONTRACT_VERSION else [])
    assert cached.prompt_summary == [line]
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_portrait_prompt_rebuild_replaces_old_contract_before_context_use():
    stale = UserPortraitProjection(user_id="audit", prompt_summary=["旧界面占位文案"])
    current = UserPortraitProjection(
        user_id="audit", prompt_summary=["用户喜欢草莓。"],
        prompt_contract_version=PORTRAIT_PROMPT_CONTRACT_VERSION,
    )
    repo = SimpleNamespace(get=AsyncMock(return_value=stale), upsert=AsyncMock(return_value=current))
    builder = SimpleNamespace(build=AsyncMock(return_value=current))
    service = UserProfileService(unified_memory=SimpleNamespace(l2=object()))
    with patch.object(service, "_memory_db_path", return_value="/unused-audit-memory.db"), patch.object(service, "_current_profile_projection", AsyncMock(return_value=None)), patch("magi.context.user_profile_service.UserPortraitProjectionRepository", return_value=repo), patch("magi.context.user_profile_service.UserPortraitProjectionBuilder", return_value=builder):
        assert await service._fetch_portrait_prompt_summary("audit") == ["用户喜欢草莓。"]
    builder.build.assert_awaited_once_with("audit")
    repo.upsert.assert_awaited_once_with(current)
