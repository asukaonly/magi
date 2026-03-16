# A4 API Runtime Bypass Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove API and transport-layer bypass paths where routers or bridge code create their own domain objects, sensors, or talk directly to runtime/global accessors instead of using DI-backed bindings.

**Architecture:** `api/` and `websocket/` should consume stable service contracts or DI-provided runtime bindings, not instantiate domain objects on demand and not re-export raw globals from owning layers. This plan keeps A4 scoped to bypass cleanup only: it exposes runtime-owned instances through container bindings, removes router-local fallbacks such as `_user_message_sensor` and `_other_memory`, and replaces API-side raw accessor re-exports with explicit bindings. It intentionally does not redesign the skills lifecycle itself; that remains A5.

**Tech Stack:** Python 3.10+, FastAPI, dependency-injector, pytest, Magi bootstrap exports

---

## File Structure

### Neutral Runtime Bindings

- Create: `backend/src/magi/core/runtime_bindings.py`
  Container-only runtime resolvers for API/transport consumers; no fallback creation.
- Modify: `backend/src/magi/core/container.py`
  Add provider slots for `other_memory`, `skill_indexer`, `skill_loader`, and `skill_executor`.
- Modify: `backend/src/magi/bootstrap/exports.py`
  Export runtime-owned `OtherMemory` and shared skills services into the DI container during bootstrap.

### API Service Contracts

- Create: `backend/src/magi/api/services/message_bus_service.py`
  Resolve the active message bus from DI without exposing raw `events.service_access` accessors to routers.
- Create: `backend/src/magi/api/services/other_memory_service.py`
  Resolve the runtime-owned `OtherMemory` instance from DI.
- Create: `backend/src/magi/api/services/user_message_sensor_service.py`
  Resolve the shared `UserMessageSensor` from DI.
- Create: `backend/src/magi/api/services/skills_runtime_service.py`
  Resolve shared skill indexer/loader/executor through DI-backed bindings.
- Create: `backend/src/magi/api/services/personality_state_service.py`
  Provide explicit personality-state operations for API callers instead of raw re-exports in `__init__.py`.
- Modify: `backend/src/magi/api/services/__init__.py`
  Export explicit service modules only; remove raw re-exports from `events.service_access`, `skills.service_access`, and `personality.current_state`.

### API Router Cleanup

- Modify: `backend/src/magi/api/routers/messages.py`
  Remove `_user_message_sensor`, `get_user_message_sensor()`, and message-bus compatibility wrappers; consume DI/service bindings only.
- Modify: `backend/src/magi/api/routers/others.py`
  Remove `_other_memory` and `get_other_memory()`; consume the runtime-owned `OtherMemory` through DI/service bindings.
- Modify: `backend/src/magi/api/routers/skills.py`
  Stop calling `skills.service_access` directly; use explicit API service bindings.
- Modify: `backend/src/magi/api/routers/personality_config.py`
  Stop using router-local compatibility wrappers for current personality state.

### Transport Cleanup

- Modify: `backend/src/magi/websocket/handlers.py`
  Replace direct message-bus and personality-global access with explicit bindings or service contracts.
- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
  Resolve the message bus through DI-backed bindings instead of direct global access.

### Tests

- Create: `backend/tests/api/test_runtime_bypass_boundaries.py`
  Source-level boundary tests proving routers no longer own object singletons or re-export raw runtime globals.
- Create: `backend/tests/core/test_runtime_bindings.py`
  Verify DI-backed runtime binding helpers fail loudly when unbound and return the bound objects when exported.
- Modify: `backend/tests/api/test_messages_api.py` or create `backend/tests/api/test_messages_router_bindings.py`
  Verify message routes use DI-provided sensor and message bus without fallback creation.
- Modify: `backend/tests/api/test_others_api.py` or create `backend/tests/api/test_others_router_bindings.py`
  Verify other-memory routes consume the runtime-owned `OtherMemory`.
- Modify: `backend/tests/api/test_skills_router.py`
  Verify skills routes continue to work through the explicit runtime binding layer.
- Modify: `backend/tests/websocket/test_bridge_lifecycle.py`
  Verify the bridge still subscribes once the DI-exposed message bus is available.

### Documentation

- Reference only: `docs/issues/layered-architecture-remediation-checklist.md`
  Mark A4 progress after implementation lands.

## Chunk 1: Lock The Boundary

### Task 1: Add failing tests for API-owned runtime bypasses

**Files:**
- Create: `backend/tests/api/test_runtime_bypass_boundaries.py`

- [ ] **Step 1: Write failing boundary tests**

```python
from pathlib import Path


def test_messages_router_does_not_define_global_user_message_sensor() -> None:
    from magi.api.routers import messages as messages_router

    source = Path(messages_router.__file__).read_text(encoding="utf-8")
    assert "_user_message_sensor" not in source
    assert "UserMessageSensor()" not in source


def test_others_router_does_not_define_global_other_memory() -> None:
    from magi.api.routers import others as others_router

    source = Path(others_router.__file__).read_text(encoding="utf-8")
    assert "_other_memory" not in source
    assert "OtherMemory(" not in source


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_runtime_bypass_boundaries.py -q`
Expected: FAIL because `messages.py`, `others.py`, and `api/services/__init__.py` still contain the bypass patterns.

- [ ] **Step 3: Commit the failing tests**

```bash
git add backend/tests/api/test_runtime_bypass_boundaries.py
git commit -m "test: cover api runtime bypass boundaries"
```

## Chunk 2: Expose Runtime-Owned Instances Through DI

### Task 2: Add explicit runtime binding helpers and container providers

**Files:**
- Create: `backend/src/magi/core/runtime_bindings.py`
- Modify: `backend/src/magi/core/container.py`
- Modify: `backend/src/magi/bootstrap/exports.py`
- Create: `backend/tests/core/test_runtime_bindings.py`

- [ ] **Step 1: Write failing tests for runtime binding helpers**

```python
def test_require_other_memory_binding_raises_when_unbound() -> None:
    from magi.core.runtime_bindings import require_other_memory

    with pytest.raises(RuntimeError, match="other_memory"):
        require_other_memory()
```

```python
def test_require_message_bus_binding_returns_bound_object() -> None:
    from dependency_injector import providers
    from magi.core.container import get_container
    from magi.core.runtime_bindings import require_message_bus

    container = get_container()
    token = object()
    container.message_bus.override(providers.Object(token))
    try:
        assert require_message_bus() is token
    finally:
        container.message_bus.reset_override()
```

- [ ] **Step 2: Add container-backed runtime resolvers**

```python
# backend/src/magi/core/runtime_bindings.py
def require_message_bus():
    instance = get_container().message_bus()
    if instance is None or type(instance).__name__ == "object":
        raise RuntimeError("message_bus binding is not initialized")
    return instance
```

```python
def require_other_memory():
    ...
```

```python
def require_skill_executor():
    ...
```

- [ ] **Step 3: Extend container provider surface**

```python
# backend/src/magi/core/container.py
other_memory = providers.Singleton(object)
skill_indexer = providers.Singleton(object)
skill_loader = providers.Singleton(object)
skill_executor = providers.Singleton(object)
```

- [ ] **Step 4: Export runtime-owned objects during bootstrap**

```python
# backend/src/magi/bootstrap/exports.py
container.other_memory.override(providers.Object(self._context.personality.other_memory))
container.skill_indexer.override(providers.Object(get_skill_indexer()))
container.skill_loader.override(providers.Object(get_skill_loader()))
container.skill_executor.override(providers.Object(get_skill_executor()))
```

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/core/test_runtime_bindings.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/core/runtime_bindings.py backend/src/magi/core/container.py backend/src/magi/bootstrap/exports.py backend/tests/core/test_runtime_bindings.py
git commit -m "refactor: expose api runtime bindings through di"
```

## Chunk 3: Remove Router-Owned Object Lifecycles

### Task 3: Remove message-router sensor and message-bus fallbacks

**Files:**
- Modify: `backend/src/magi/api/routers/messages.py`
- Create or modify: `backend/src/magi/api/services/message_bus_service.py`
- Create or modify: `backend/src/magi/api/services/user_message_sensor_service.py`
- Create: `backend/tests/api/test_messages_router_bindings.py`

- [ ] **Step 1: Write failing router-binding tests**

```python
@pytest.mark.asyncio
async def test_sensor_status_uses_di_bound_user_message_sensor(monkeypatch) -> None:
    sensor = _FakeUserMessageSensor()
    monkeypatch.setattr("magi.api.services.user_message_sensor_service.require_user_message_sensor", lambda: sensor)

    response = await get_sensor_status()

    assert response["enabled"] is sensor.enabled
```

- [ ] **Step 2: Remove router-local globals and wrappers**

```python
# delete:
_user_message_sensor = None
def get_user_message_sensor() -> UserMessageSensor: ...
def get_message_bus(): ...
def set_message_bus(...): ...
```

- [ ] **Step 3: Use explicit service bindings**

```python
from ..services.message_bus_service import require_message_bus
from ..services.user_message_sensor_service import require_user_message_sensor
```

- [ ] **Step 4: Run focused message-router tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_messages_router_bindings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/messages.py backend/src/magi/api/services/message_bus_service.py backend/src/magi/api/services/user_message_sensor_service.py backend/tests/api/test_messages_router_bindings.py
git commit -m "refactor: remove message router runtime fallbacks"
```

### Task 4: Remove other-memory router fallback construction

**Files:**
- Modify: `backend/src/magi/api/routers/others.py`
- Create or modify: `backend/src/magi/api/services/other_memory_service.py`
- Create: `backend/tests/api/test_others_router_bindings.py`

- [ ] **Step 1: Write failing tests for other-memory DI resolution**

```python
def test_list_profiles_uses_bound_other_memory(monkeypatch) -> None:
    memory = _FakeOtherMemory()
    monkeypatch.setattr("magi.api.services.other_memory_service.require_other_memory", lambda: memory)
    ...
```

- [ ] **Step 2: Remove `_other_memory` and `get_other_memory()`**

```python
# delete:
_other_memory = None
def get_other_memory() -> OtherMemory: ...
```

- [ ] **Step 3: Replace with explicit service binding**

```python
from ..services.other_memory_service import require_other_memory
```

- [ ] **Step 4: Run focused other-memory tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_others_router_bindings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/others.py backend/src/magi/api/services/other_memory_service.py backend/tests/api/test_others_router_bindings.py
git commit -m "refactor: bind other memory through api services"
```

## Chunk 4: Remove Raw Runtime Re-Exports From API/Transport

### Task 5: Replace `api/services/__init__.py` raw re-exports with explicit service modules

**Files:**
- Create: `backend/src/magi/api/services/message_bus_service.py`
- Create: `backend/src/magi/api/services/other_memory_service.py`
- Create: `backend/src/magi/api/services/user_message_sensor_service.py`
- Create: `backend/src/magi/api/services/skills_runtime_service.py`
- Create: `backend/src/magi/api/services/personality_state_service.py`
- Modify: `backend/src/magi/api/services/__init__.py`
- Modify: `backend/src/magi/api/routers/skills.py`
- Modify: `backend/src/magi/api/routers/personality_config.py`

- [ ] **Step 1: Write a failing test for `api.services` exports**

```python
def test_api_services_exports_explicit_modules_only() -> None:
    from magi.api import services as api_services

    assert hasattr(api_services, "require_message_bus")
    assert not hasattr(api_services, "get_message_bus")
    assert not hasattr(api_services, "get_skill_executor")
```

- [ ] **Step 2: Add explicit service modules**

```python
# backend/src/magi/api/services/skills_runtime_service.py
def require_skill_executor():
    return require_runtime_binding("skill_executor")
```

```python
# backend/src/magi/api/services/personality_state_service.py
def get_current_personality_name() -> str:
    return personality.current_state.get_current_personality()
```

- [ ] **Step 3: Update API routers to consume the new services**

```python
from ..services.skills_runtime_service import require_skill_executor
from ..services.personality_state_service import get_current_personality_name
```

- [ ] **Step 4: Run focused router/service tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_runtime_bypass_boundaries.py tests/api/test_skills_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/services/message_bus_service.py backend/src/magi/api/services/other_memory_service.py backend/src/magi/api/services/user_message_sensor_service.py backend/src/magi/api/services/skills_runtime_service.py backend/src/magi/api/services/personality_state_service.py backend/src/magi/api/services/__init__.py backend/src/magi/api/routers/skills.py backend/src/magi/api/routers/personality_config.py backend/tests/api/test_runtime_bypass_boundaries.py backend/tests/api/test_skills_router.py
git commit -m "refactor: replace api runtime reexports with services"
```

### Task 6: Update transport consumers to use explicit bindings

**Files:**
- Modify: `backend/src/magi/websocket/handlers.py`
- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
- Modify: `backend/tests/websocket/test_bridge_lifecycle.py`

- [ ] **Step 1: Write a failing bridge test that expects DI-backed message-bus resolution**

```python
@pytest.mark.asyncio
async def test_websocket_bridge_reads_message_bus_from_runtime_bindings(...):
    ...
```

- [ ] **Step 2: Replace direct globals in transport**

```python
from ..core.runtime_bindings import require_message_bus
from ..api.services.personality_state_service import get_current_personality_name
```

- [ ] **Step 3: Run focused transport tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_bridge_lifecycle.py tests/api/test_runtime_bypass_boundaries.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/websocket/handlers.py backend/src/magi/websocket/bridge_lifecycle.py backend/tests/websocket/test_bridge_lifecycle.py backend/tests/api/test_runtime_bypass_boundaries.py
git commit -m "refactor: remove transport runtime global access"
```

## Chunk 5: Final Regression And Cleanup

### Task 7: Verify A4 end-to-end and lock the boundary

**Files:**
- Modify: `backend/tests/api/test_runtime_bypass_boundaries.py`
- Modify: `backend/tests/api/test_messages_router_bindings.py`
- Modify: `backend/tests/api/test_others_router_bindings.py`
- Modify: `backend/tests/websocket/test_bridge_lifecycle.py`

- [ ] **Step 1: Add final assertions for no bypass leftovers**

```python
assert "_user_message_sensor" not in source
assert "_other_memory" not in source
assert "events.service_access" not in source
assert "skills.service_access" not in source
```

- [ ] **Step 2: Run the A4 regression suite**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_runtime_bypass_boundaries.py tests/core/test_runtime_bindings.py tests/api/test_messages_router_bindings.py tests/api/test_others_router_bindings.py tests/api/test_skills_router.py tests/websocket/test_bridge_lifecycle.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/api/test_runtime_bypass_boundaries.py backend/tests/core/test_runtime_bindings.py backend/tests/api/test_messages_router_bindings.py backend/tests/api/test_others_router_bindings.py backend/tests/api/test_skills_router.py backend/tests/websocket/test_bridge_lifecycle.py
git commit -m "refactor: finalize api runtime bypass cleanup"
```

## Notes

- This plan intentionally does **not** unify or redesign the skills lifecycle. It only ensures API and transport consumers stop reaching into `skills.service_access` directly; A5 remains responsible for eliminating duplicate skills lifecycle ownership.
- This plan intentionally does **not** redesign owning-layer state modules such as `personality.current_state`. It only stops `api/services/__init__.py` and router-level wrappers from re-exporting those globals as the API contract.
- `UserMessageSensor` may still be container-owned in A4. The key requirement is that routers stop creating fallback singletons themselves.
- If `bootstrap/exports.py` cannot safely export one of the skill bindings because the shared skills service is uninitialized at startup, stop and split that binding into a follow-up under A5 instead of reintroducing API-side fallback creation.

## Verification Handoff

After the last task, run the full A4 regression suite once more:

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_runtime_bypass_boundaries.py tests/core/test_runtime_bindings.py tests/api/test_messages_router_bindings.py tests/api/test_others_router_bindings.py tests/api/test_skills_router.py tests/websocket/test_bridge_lifecycle.py -q`
Expected: PASS

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a4-api-runtime-bypass-cleanup.md`. Ready to execute?
