"""Tests for UserProfileService backed by L2 stores."""

from __future__ import annotations

import unittest

from magi.context.user_profile_service import UserProfileService


class _FakeL2EntityCatalog:
    async def list_entities(self, entity_ids=None, **kwargs):
        if entity_ids and entity_ids[0] == "user:alice":
            return [{"entity_id": "user:alice", "canonical_name": "Alice", "aliases": ["ali"]}]
        return []


class _FakeL2Store:
    async def get_tom_snapshot(self, entity_id=None, entity_type=None):
        if entity_id == "user:alice":
            return {"preferences": {"language": "zh-CN", "theme": "dark"}}
        return None


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

    async def test_get_preference_summary_returns_empty_for_missing_entity(self):
        svc = UserProfileService(unified_memory=_FakeUnifiedMemory())
        prefs = await svc.get_preference_summary("nobody")
        self.assertEqual(prefs, {})

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


if __name__ == "__main__":
    unittest.main()
