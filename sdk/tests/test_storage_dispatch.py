from dataclasses import dataclass
from typing import Protocol

import pytest

from magi_plugin_sdk.storage import StorageCall
from magi_plugin_sdk.storage_dispatch import RepositoryDispatcher


@dataclass
class Record:
    identifier: str
    revision: int


class Contract(Protocol):
    async def save(self, record: Record, *, replace: bool = False) -> Record: ...


class Repository:
    def __init__(self):
        self.calls = []

    async def save(self, **kwargs):
        self.calls.append(kwargs)
        assert isinstance(kwargs["record"], Record)
        return kwargs["record"]

    async def delete_everything(self):
        raise AssertionError("Private operation must never be dispatched")


@pytest.mark.asyncio
async def test_dispatch_validates_commands_and_uses_contract_defaults():
    repository = Repository()
    dispatcher = RepositoryDispatcher({"records": repository}, {"records": ("save",)}, {"records": Contract})
    request = StorageCall(session_id="s", repository="records", operation="save", arguments={"record": {"identifier": "a", "revision": 1}})
    result = await dispatcher.invoke(request)
    assert result.value == {"identifier": "a", "revision": 1}
    assert repository.calls == [{"record": Record("a", 1), "replace": False}]
    for arguments in ({"record": {}}, {"record": {"identifier": "a", "revision": 1}, "unexpected": True}):
        assert (await dispatcher.invoke(request.model_copy(update={"arguments": arguments}))).error == "invalid"
    assert (await dispatcher.invoke(request.model_copy(update={"operation": "delete_everything"}))).error == "invalid"
    assert len(repository.calls) == 1
