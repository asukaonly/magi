from __future__ import annotations

import pytest

from magi.api.routers import others as others_router


class _FakeProfile:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def to_dict(self) -> dict[str, str]:
        return {"user_id": self.user_id}


class _FakeOtherMemory:
    def list_profiles(self):
        return [_FakeProfile("u1"), _FakeProfile("u2")]


@pytest.mark.asyncio
async def test_list_profiles_uses_bound_other_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = _FakeOtherMemory()
    monkeypatch.setattr(others_router, "require_other_memory", lambda: memory)

    response = await others_router.list_profiles()

    assert response.success is True
    assert response.data == {
        "profiles": [{"user_id": "u1"}, {"user_id": "u2"}],
        "count": 2,
    }
