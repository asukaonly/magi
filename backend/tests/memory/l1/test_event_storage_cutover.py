"""Pre-plugin metadata is upgraded only for the proven original owner offline."""

import json
import pytest
from _shared.storage_plugins import start, stop
from magi.bootstrap.storage_selection import BINDING_PATHS, binding_file
from magi.bootstrap.storage_transfer import adopt_current_binding
from magi.config.storage_models import StructuredStorageSettings
from magi.utils.runtime import RuntimePaths


@pytest.mark.parametrize("domain,identity", [("chat", "local-chat-v1"), ("memory_events", "local-l1-events-v1"), ("channels", "local-channels-v1")])
async def test_adoption_preserves_center_and_rejects_wrong_owner(tmp_path, domain, identity):
    paths = RuntimePaths(base_dir=tmp_path)
    context, module = await start(paths, StructuredStorageSettings())
    await stop(context, module)
    before = binding_file(paths, domain).read_or_create()
    file = paths.data_dir / BINDING_PATHS[domain]
    old = {"version": 1, "center_id": before.center_id, "pending": None,
           "active": {"kind": "sqlite", "identity": "wrong-owner"}}
    file.write_text(json.dumps(old))
    with pytest.raises(ValueError, match="same physical"):
        await adopt_current_binding(paths, domain)
    assert json.loads(file.read_text()) == old
    old["active"]["identity"] = identity
    file.write_text(json.dumps(old))
    with pytest.raises(ValueError):
        await start(paths, StructuredStorageSettings())
    assert (await adopt_current_binding(paths, domain))["status"] == "adopted"
    after = binding_file(paths, domain).read_or_create()
    assert after.center_id == before.center_id and after.active == before.active
