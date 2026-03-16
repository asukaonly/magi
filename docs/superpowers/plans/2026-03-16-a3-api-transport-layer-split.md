# A3 API And Transport Layer Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate `L13 External Services` from `L14 Connection And Transport` so `api/` only owns product-facing service endpoints while HTTP/WebSocket transport concerns live under `websocket/`.

**Architecture:** Reclaim `backend/src/magi/websocket/` as the real L14 transport package and remove the current split where native WebSocket transport lives under `api/` while `websocket/` still contains deprecated Socket.IO code. Move FastAPI app assembly, HTTP middleware, native WebSocket connection management, and the event-to-WebSocket bridge into L14; keep `api/` focused on routers, response DTOs, read services, and route registration only.

**Tech Stack:** Python 3.10+, FastAPI, native WebSocket support, pytest, Magi layered lifecycle modules

---

## File Structure

### L13 External Services

- Create: `backend/src/magi/api/routes.py`
  Own route registration only; no FastAPI construction, middleware, or WebSocket registration.
- Modify: `backend/src/magi/api/__init__.py`
  Export API-layer utilities only; remove app-factory ownership.
- Keep: `backend/src/magi/api/routers/*`
  Continue owning product-facing endpoint handlers.
- Keep: `backend/src/magi/api/services/*`
  Continue owning API read services and service adapters.
- Keep: `backend/src/magi/api/responses.py`
  API response DTOs remain in L13.

### L14 Connection And Transport

- Create: `backend/src/magi/websocket/http_app.py`
  Own FastAPI app construction, OpenAPI endpoints, middleware wiring, static mounting, and transport registration.
- Create: `backend/src/magi/websocket/http_middleware.py`
  Own CORS, request logging, language context, and desktop-session transport auth middleware.
- Create: `backend/src/magi/websocket/connection_manager.py`
  Move the native WebSocket connection manager out of `api/`.
- Create: `backend/src/magi/websocket/router.py`
  Move `/ws` endpoint registration and message-loop transport handling out of `api/`.
- Create: `backend/src/magi/websocket/handlers.py`
  Move native WebSocket message handlers out of `api/`.
- Create: `backend/src/magi/websocket/bridge_lifecycle.py`
  Move the event-bus-to-WebSocket bridge lifecycle out of `api/`.
- Modify: `backend/src/magi/websocket/__init__.py`
  Export the real L14 transport surface; remove deprecation warning and Socket.IO wording.
- Delete: `backend/src/magi/websocket/server.py`
  Remove the deprecated Socket.IO server implementation.
- Delete: `backend/src/magi/websocket/events.py`
  Remove deprecated Socket.IO event push helpers.

### Application Composition

- Modify: `backend/src/magi/backend_app.py`
  Build the backend with the transport app factory and transport-owned bridge lifecycle.
- Modify: `backend/src/magi/core/container.py`
  Rewire handler imports to the new `magi.websocket.*` transport paths.

### Deletion Path

- Delete: `backend/src/magi/api/app.py`
  FastAPI app assembly should not stay in L13.
- Delete: `backend/src/magi/api/middleware.py`
  HTTP middleware is transport-layer code.
- Delete: `backend/src/magi/api/connection_manager.py`
  Connection management belongs to L14.
- Delete: `backend/src/magi/api/websocket/__init__.py`
- Delete: `backend/src/magi/api/websocket/router.py`
- Delete: `backend/src/magi/api/websocket/handlers.py`
- Delete: `backend/src/magi/api/websocket_bridge_lifecycle.py`

### Tests

- Create: `backend/tests/websocket/test_transport_layer_boundaries.py`
  Verify transport ownership moved under `magi.websocket.*`.
- Create: `backend/tests/websocket/test_connection_manager.py`
  Move connection-manager behavior tests to the transport package test area.
- Create: `backend/tests/websocket/test_bridge_lifecycle.py`
  Move bridge lifecycle coverage to the transport package test area.
- Create: `backend/tests/websocket/test_http_app.py`
  Verify the transport app factory assembles middleware, API routes, and `/ws`.
- Modify: `backend/tests/api/test_personality_presets_router.py`
  Stop importing the deleted `magi.api.app.create_app`.
- Delete: `backend/tests/api/test_connection_manager.py`
  Replace with transport-package tests.
- Delete or move: `backend/tests/api/test_backend_app_websocket_bridge.py`
  Replace with `tests/websocket/test_bridge_lifecycle.py`.

### Documentation

- Reference only: `docs/issues/layered-architecture-remediation-checklist.md`
  Mark A3 progress after implementation lands.

## Chunk 1: Reclaim The L14 WebSocket Package

### Task 1: Prove transport ownership is still misplaced

**Files:**
- Create: `backend/tests/websocket/test_transport_layer_boundaries.py`

- [ ] **Step 1: Write failing ownership tests**

```python
from pathlib import Path


def test_connection_manager_lives_in_websocket_layer() -> None:
    from magi.websocket.connection_manager import ConnectionManager

    assert ConnectionManager.__module__ == "magi.websocket.connection_manager"


def test_websocket_bridge_lifecycle_lives_in_websocket_layer() -> None:
    from magi.websocket.bridge_lifecycle import WebSocketBridgeLifecycleModule

    assert WebSocketBridgeLifecycleModule.__module__ == "magi.websocket.bridge_lifecycle"


def test_api_route_registration_does_not_import_transport() -> None:
    from magi.api import routes as api_routes

    source = Path(api_routes.__file__).read_text(encoding="utf-8")

    assert "register_websocket" not in source
    assert "FastAPI(" not in source
```

- [ ] **Step 2: Run the new ownership tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_transport_layer_boundaries.py -q`
Expected: FAIL because `magi.websocket.connection_manager`, `magi.websocket.bridge_lifecycle`, and `magi.api.routes` do not exist yet.

- [ ] **Step 3: Commit the failing tests**

```bash
git add backend/tests/websocket/test_transport_layer_boundaries.py
git commit -m "test: cover transport layer ownership"
```

### Task 2: Move native WebSocket transport out of `api/`

**Files:**
- Create: `backend/src/magi/websocket/connection_manager.py`
- Create: `backend/src/magi/websocket/router.py`
- Create: `backend/src/magi/websocket/handlers.py`
- Modify: `backend/src/magi/websocket/__init__.py`
- Modify: `backend/src/magi/core/container.py`
- Create: `backend/tests/websocket/test_connection_manager.py`
- Delete: `backend/src/magi/api/connection_manager.py`
- Delete: `backend/src/magi/api/websocket/__init__.py`
- Delete: `backend/src/magi/api/websocket/router.py`
- Delete: `backend/src/magi/api/websocket/handlers.py`
- Delete: `backend/tests/api/test_connection_manager.py`

- [ ] **Step 1: Copy the native WebSocket transport into `magi.websocket`**

```python
# backend/src/magi/websocket/connection_manager.py
class ConnectionManager:
    ...


manager = ConnectionManager()
```

```python
# backend/src/magi/websocket/router.py
def register_websocket(app: FastAPI, manager: ConnectionManager = manager, path: str = "/ws") -> None:
    ...
```

```python
# backend/src/magi/websocket/handlers.py
@handler_registry.register("subscribe")
async def handle_subscribe(...):
    ...
```

- [ ] **Step 2: Update imports to the new transport package**

```python
# backend/src/magi/core/container.py
"magi.websocket.handlers",
```

```python
# backend/src/magi/websocket/__init__.py
from .connection_manager import ConnectionManager, manager
from .router import register_websocket, websocket_endpoint
from .handlers import MessageHandlerRegistry, WebSocketContext, handler_registry
```

- [ ] **Step 3: Move the connection-manager test into the transport test area**

```python
# backend/tests/websocket/test_connection_manager.py
from magi.websocket.connection_manager import ConnectionManager
```

- [ ] **Step 4: Run focused transport tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_transport_layer_boundaries.py tests/websocket/test_connection_manager.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/websocket/connection_manager.py backend/src/magi/websocket/router.py backend/src/magi/websocket/handlers.py backend/src/magi/websocket/__init__.py backend/src/magi/core/container.py backend/tests/websocket/test_transport_layer_boundaries.py backend/tests/websocket/test_connection_manager.py
git rm backend/src/magi/api/connection_manager.py backend/src/magi/api/websocket/__init__.py backend/src/magi/api/websocket/router.py backend/src/magi/api/websocket/handlers.py backend/tests/api/test_connection_manager.py
git commit -m "refactor: move websocket transport into transport layer"
```

## Chunk 2: Move App Assembly Into L14

### Task 3: Move the WebSocket bridge lifecycle into `websocket/`

**Files:**
- Create: `backend/src/magi/websocket/bridge_lifecycle.py`
- Modify: `backend/src/magi/backend_app.py`
- Create: `backend/tests/websocket/test_bridge_lifecycle.py`
- Delete: `backend/src/magi/api/websocket_bridge_lifecycle.py`
- Delete or move: `backend/tests/api/test_backend_app_websocket_bridge.py`

- [ ] **Step 1: Write a failing bridge-lifecycle test in the transport package**

```python
from magi.backend_app import create_backend_app


async def test_websocket_bridge_subscribes_after_runtime_message_bus_ready(...):
    ...
```

- [ ] **Step 2: Move the bridge lifecycle into `magi.websocket.bridge_lifecycle`**

```python
# backend/src/magi/backend_app.py
from .websocket.bridge_lifecycle import WebSocketBridgeLifecycleModule
```

- [ ] **Step 3: Move the bridge test to the transport test area**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_bridge_lifecycle.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/websocket/bridge_lifecycle.py backend/src/magi/backend_app.py backend/tests/websocket/test_bridge_lifecycle.py
git rm backend/src/magi/api/websocket_bridge_lifecycle.py backend/tests/api/test_backend_app_websocket_bridge.py
git commit -m "refactor: move websocket bridge lifecycle to transport"
```

### Task 4: Move FastAPI app construction and HTTP middleware into the transport layer

**Files:**
- Create: `backend/src/magi/api/routes.py`
- Create: `backend/src/magi/websocket/http_app.py`
- Create: `backend/src/magi/websocket/http_middleware.py`
- Modify: `backend/src/magi/backend_app.py`
- Modify: `backend/src/magi/api/__init__.py`
- Modify: `backend/tests/api/test_personality_presets_router.py`
- Create: `backend/tests/websocket/test_http_app.py`
- Delete: `backend/src/magi/api/app.py`
- Delete: `backend/src/magi/api/middleware.py`

- [ ] **Step 1: Write a failing transport-app test**

```python
from fastapi.testclient import TestClient


def test_transport_app_registers_api_routes_and_websocket(monkeypatch) -> None:
    from magi.websocket.http_app import create_transport_app

    client = TestClient(create_transport_app())

    assert client.get("/api/health").status_code == 200
```

- [ ] **Step 2: Extract route registration into the API layer**

```python
# backend/src/magi/api/routes.py
def register_api_routes(app: FastAPI) -> None:
    app.include_router(...)
```

- [ ] **Step 3: Move HTTP middleware and app factory into `magi.websocket`**

```python
# backend/src/magi/websocket/http_app.py
def create_transport_app(*, lifespan: Any = None) -> FastAPI:
    app = FastAPI(...)
    add_cors_middleware(app)
    app.add_middleware(ErrorHandler)
    ...
    register_api_routes(app)
    register_websocket(app)
    return app
```

- [ ] **Step 4: Update backend entrypoints and tests**

```python
# backend/src/magi/backend_app.py
from .websocket.http_app import create_transport_app
```

```python
# backend/tests/api/test_personality_presets_router.py
from magi.websocket.http_app import create_transport_app
```

- [ ] **Step 5: Run focused HTTP transport tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_http_app.py tests/api/test_personality_presets_router.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/api/routes.py backend/src/magi/websocket/http_app.py backend/src/magi/websocket/http_middleware.py backend/src/magi/backend_app.py backend/src/magi/api/__init__.py backend/tests/websocket/test_http_app.py backend/tests/api/test_personality_presets_router.py
git rm backend/src/magi/api/app.py backend/src/magi/api/middleware.py
git commit -m "refactor: move http app assembly to transport layer"
```

## Chunk 3: Remove Legacy Transport Paths

### Task 5: Delete deprecated Socket.IO transport and finalize L14 exports

**Files:**
- Modify: `backend/src/magi/websocket/__init__.py`
- Delete: `backend/src/magi/websocket/server.py`
- Delete: `backend/src/magi/websocket/events.py`
- Modify: `backend/tests/websocket/test_transport_layer_boundaries.py`
- Modify: `backend/tests/websocket/test_http_app.py`

- [ ] **Step 1: Add a failing test for the old transport path removal**

```python
import importlib
import pytest


def test_legacy_socketio_transport_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("magi.websocket.server")
```

- [ ] **Step 2: Rewrite `magi.websocket.__init__` as the real transport package**

```python
__all__ = [
    "ConnectionManager",
    "manager",
    "register_websocket",
    "websocket_endpoint",
    "WebSocketBridgeLifecycleModule",
    "create_transport_app",
]
```

- [ ] **Step 3: Delete the deprecated Socket.IO files**

```bash
git rm backend/src/magi/websocket/server.py backend/src/magi/websocket/events.py
```

- [ ] **Step 4: Run transport regression tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_transport_layer_boundaries.py tests/websocket/test_connection_manager.py tests/websocket/test_bridge_lifecycle.py tests/websocket/test_http_app.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/websocket/__init__.py backend/tests/websocket/test_transport_layer_boundaries.py backend/tests/websocket/test_http_app.py
git rm backend/src/magi/websocket/server.py backend/src/magi/websocket/events.py
git commit -m "refactor: remove legacy transport paths"
```

### Task 6: Final boundary cleanup and regression verification

**Files:**
- Modify: `backend/tests/websocket/test_transport_layer_boundaries.py`
- Modify: `backend/tests/websocket/test_http_app.py`
- Modify: `backend/tests/api/test_personality_presets_router.py`
- Modify: `backend/src/magi/backend_app.py`

- [ ] **Step 1: Lock in the final ownership assertions**

```python
def test_backend_app_builds_transport_app() -> None:
    source = Path(backend_app.__file__).read_text(encoding="utf-8")

    assert "from .websocket.http_app import create_transport_app" in source
    assert "from .api.app import create_app" not in source
```

- [ ] **Step 2: Run the A3 regression suite**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_transport_layer_boundaries.py tests/websocket/test_connection_manager.py tests/websocket/test_bridge_lifecycle.py tests/websocket/test_http_app.py tests/api/test_personality_presets_router.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/src/magi/backend_app.py backend/tests/websocket/test_transport_layer_boundaries.py backend/tests/websocket/test_http_app.py backend/tests/api/test_personality_presets_router.py
git commit -m "refactor: finalize api and transport split"
```

## Notes

- This plan intentionally keeps `api/routers/*` in L13 even though they still use FastAPI decorators; the split here is about ownership of transport assembly, connection lifecycle, and protocol plumbing.
- This plan intentionally does **not** include A4 API-side dependency cleanup beyond the imports that must move when transport code leaves `api/`.
- This plan intentionally does **not** rename transport event payloads or WebSocket message DTOs beyond what is required for directory and ownership alignment.
- `api/avatar_paths.py` may remain in L13 during A3 because it is still used to produce product-facing avatar URLs in router responses. If transport static-file mounting later needs a cleaner home, handle that in a follow-up without blocking A3.

## Verification Handoff

After the last task, run the full A3 regression suite once more:

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/websocket/test_transport_layer_boundaries.py tests/websocket/test_connection_manager.py tests/websocket/test_bridge_lifecycle.py tests/websocket/test_http_app.py tests/api/test_personality_presets_router.py -q`
Expected: PASS

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a3-api-transport-layer-split.md`. Ready to execute?
