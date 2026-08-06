"""Tests for UserProfileService backed by L2 stores."""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from magi.context.user_profile_service import UserProfileService


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
                    "trait_family": "interest_profile",
                    "trait_name": "interest.magi",
                    "trait_value": "Magi 记忆系统",
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


class _BrokenRevisionL2Store(_FakeL2Store):
    async def current_subject_revision(self, subject_key: str) -> int:
        raise RuntimeError(f"cannot read {subject_key}")


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

    async def test_get_display_name_returns_unknown_for_missing_entity(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("nobody")
        self.assertEqual(name, "unknown")

    async def test_get_display_name_falls_back_to_tentative_assertion_preferences(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("pending")
        self.assertEqual(name, "哈基米")

    async def test_get_display_name_prefers_address_preference_over_canonical_name(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("hakimi")
        self.assertEqual(name, "哈基米")

    async def test_get_display_name_returns_unknown_when_no_unified_memory(self):
        svc = UserProfileService(unified_memory=None)
        name = await svc.get_display_name("alice")
        self.assertEqual(name, "unknown")

    async def test_get_display_name_returns_unknown_when_no_catalog(self):
        um = _FakeUnifiedMemory()
        um.l2_entity_catalog = None
        svc = UserProfileService(unified_memory=um)
        name = await svc.get_display_name("alice")
        self.assertEqual(name, "unknown")

    async def test_get_display_name_returns_unknown_on_error(self):
        svc = UserProfileService(unified_memory=_BrokenUnifiedMemory())
        name = await svc.get_display_name("alice")
        self.assertEqual(name, "unknown")

    async def test_get_display_name_returns_unknown_for_empty_user_id(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        name = await svc.get_display_name("")
        self.assertEqual(name, "unknown")

    async def test_get_preference_summary_returns_preferences(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("alice")
        self.assertEqual(prefs, {"language": "zh-CN", "theme": "dark"})

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

    async def test_get_preference_summary_returns_empty_for_missing_entity(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("nobody")
        self.assertEqual(prefs, {})

    async def test_get_preference_summary_falls_back_to_tentative_assertions(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("pending")
        self.assertEqual(prefs, {"address.preferred": "哈基米"})

    async def test_get_preference_summary_returns_empty_when_no_unified_memory(self):
        svc = UserProfileService(unified_memory=None)
        prefs = await svc.get_preference_summary("alice")
        self.assertEqual(prefs, {})

    async def test_get_preference_summary_returns_empty_when_no_l2(self):
        um = _FakeUnifiedMemory()
        um.l2 = None
        svc = UserProfileService(unified_memory=um)
        prefs = await svc.get_preference_summary("alice")
        self.assertEqual(prefs, {})

    async def test_get_preference_summary_returns_empty_on_error(self):
        svc = UserProfileService(unified_memory=_BrokenUnifiedMemory())
        prefs = await svc.get_preference_summary("alice")
        self.assertEqual(prefs, {})

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

    async def test_revision_read_failure_reuses_short_lived_last_good_cache(self):
        um = _FakeUnifiedMemory()
        um.l2 = _BrokenRevisionL2Store()
        svc = UserProfileService(unified_memory=um, cache_ttl=300)

        await svc.get_display_name("alice")
        await svc.get_display_name("alice")

        self.assertEqual(um.l2_entity_catalog.call_count, 1)

    async def test_cache_returns_independent_dict_copy(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs1 = await svc.get_preference_summary("alice")
        prefs1["mutated"] = True
        prefs2 = await svc.get_preference_summary("alice")
        self.assertNotIn("mutated", prefs2)

    async def test_invalidate_single_user(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um)

        await svc.get_display_name("alice")
        self.assertEqual(um.l2_entity_catalog.call_count, 1)

        svc.invalidate("alice")
        await svc.get_display_name("alice")
        self.assertEqual(um.l2_entity_catalog.call_count, 2)

    async def test_invalidate_all(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um)

        await svc.get_display_name("alice")
        svc.invalidate()
        await svc.get_display_name("alice")
        self.assertEqual(um.l2_entity_catalog.call_count, 2)

    async def test_cache_expires_after_ttl(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um, cache_ttl=0)  # immediate expiry

        await svc.get_display_name("alice")
        await svc.get_display_name("alice")
        # With TTL=0, every call re-fetches.
        self.assertEqual(um.l2_entity_catalog.call_count, 2)

    async def test_empty_cache_uses_shorter_ttl(self):
        um = _FakeUnifiedMemory()
        svc = UserProfileService(unified_memory=um, cache_ttl=300, empty_cache_ttl=0)

        await svc.get_display_name("nobody")
        await svc.get_display_name("nobody")

        self.assertEqual(um.l2_entity_catalog.call_count, 2)


if __name__ == "__main__":
    unittest.main()
