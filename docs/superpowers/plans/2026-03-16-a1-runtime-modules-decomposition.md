# A1 Thin Bootstrap And Layer-Owned Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `backend/src/magi/runtime/runtime_modules.py` and replace it with a thin `runtime/bootstrap.py` that only assembles lifecycle modules exposed by the owning layers.

**Architecture:** Each layer owns its own lifecycle definition in its own package, for example `config/lifecycle.py`, `llm/lifecycle.py`, `memory/lifecycle.py`, and so on. `runtime/bootstrap.py` remains only as the startup/shutdown composition root that creates shared bootstrap context, collects layer-provided `LifecycleModule` instances in order, and hands them to `ModuleLifecycleOrchestrator`.

**Tech Stack:** Python 3.10+, pytest, dependency-injector, Magi runtime lifecycle modules

---

## File Structure

### Shared bootstrap orchestration

- Modify: `backend/src/magi/runtime/bootstrap.py`
  Reduce bootstrap to thin orchestration only. It should create bootstrap context, collect layer-owned lifecycle modules, and run the orchestrator.
- Modify: `backend/src/magi/runtime/__init__.py`
  Keep exports aligned if import paths or helper exposure change.
- Modify: `backend/src/magi/runtime/lifecycle.py`
  Only if small helper additions are needed for the new composition shape.
- Delete: `backend/src/magi/runtime/runtime_modules.py`
  Remove the monolithic runtime bootstrap file after all layer lifecycle entrypoints are wired.

### Shared runtime bootstrap context

- Create: `backend/src/magi/runtime/bootstrap_context.py`
  Define the thin shared context used across layer lifecycle modules.

Recommended context slices:

- `core`
  runtime paths, config, database initializer
- `llm`
  scenario LLM pool, core adapter, usage store
- `memory`
  unified memory, memory integration
- `personality`
  self memory, other memory, current personality
- `context`
  scenario prompts store
- `runtime`
  sensor hub, action emitter, task agent manager, agent runtime
- `timeline`
  timeline service
- `scheduler`
  scheduler service, scheduler bootstrap if still temporarily needed
- `maintenance`
  maintenance daemon

### Layer-owned lifecycle entrypoints

- Create: `backend/src/magi/config/lifecycle.py`
  Export the configuration lifecycle module.
- Create: `backend/src/magi/events/lifecycle.py`
  Export the message bus lifecycle module.
- Create: `backend/src/magi/plugins/lifecycle.py`
  Export the plugin system lifecycle module.
- Create: `backend/src/magi/llm/lifecycle.py`
  Export the LLM runtime lifecycle module.
- Create: `backend/src/magi/memory/lifecycle.py`
  Export the memory store lifecycle module.
- Create: `backend/src/magi/personality/lifecycle.py`
  Export the personality lifecycle module.
- Create: `backend/src/magi/context/lifecycle.py`
  Export the context lifecycle module.
- Create: `backend/src/magi/tools/lifecycle.py`
  Export the tools and skills lifecycle module.
- Create: `backend/src/magi/awareness/lifecycle.py`
  Export the sensors and actions lifecycle module.
- Create: `backend/src/magi/agent/lifecycle.py`
  Export the agent runtime lifecycle module.
- Create: `backend/src/magi/timeline/lifecycle.py`
  Export the timeline lifecycle module.
- Create: `backend/src/magi/scheduler/lifecycle.py`
  Export the scheduler engine lifecycle module.

### Tests

- Create: `backend/tests/runtime/test_layer_lifecycle_modules.py`
  Verify each layer exposes lifecycle modules from its own package and that bootstrap assembles them in the expected order.
- Modify: `backend/tests/runtime/test_bootstrap_llm_selection.py`
  Only if bootstrap import paths or state helpers move.
- Re-run: `backend/tests/runtime/test_lifecycle_orchestrator.py`
  Guard the generic lifecycle engine.
- Re-run: `backend/tests/api/test_backend_app_websocket_bridge.py`
  Guard backend startup wiring against bootstrap regressions.

### Documentation

- Reference only: `docs/issues/layered-architecture-remediation-checklist.md`
  Mark A1 progress after implementation lands.

## Chunk 1: Shared Bootstrap Context

### Task 1: Introduce a thin shared bootstrap context outside `runtime_modules.py`

**Files:**
- Create: `backend/src/magi/runtime/bootstrap_context.py`
- Create: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write the failing bootstrap-context test**

```python
from magi.runtime.bootstrap_context import RuntimeBootstrapContext


def test_runtime_bootstrap_context_exposes_layer_slices() -> None:
    context = RuntimeBootstrapContext()

    assert hasattr(context, "core")
    assert hasattr(context, "llm")
    assert hasattr(context, "memory")
    assert hasattr(context, "runtime")
    assert hasattr(context, "scheduler")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py::test_runtime_bootstrap_context_exposes_layer_slices -v`
Expected: FAIL because `RuntimeBootstrapContext` does not exist yet.

- [ ] **Step 3: Create a slice-based bootstrap context**

```python
@dataclass
class CoreBootstrapState:
    config: AppConfig | None = None
    runtime_paths: RuntimePaths | None = None
    db_initializer: DatabaseInitializer | None = None


@dataclass
class RuntimeBootstrapContext:
    core: CoreBootstrapState = field(default_factory=CoreBootstrapState)
    llm: LLMBootstrapState = field(default_factory=LLMBootstrapState)
    memory: MemoryBootstrapState = field(default_factory=MemoryBootstrapState)
    runtime: RuntimeLayerState = field(default_factory=RuntimeLayerState)
```

- [ ] **Step 4: Add a regression test for required helper behavior**

```python
import pytest

from magi.runtime.bootstrap_context import RuntimeBootstrapContext, require_initialized


def test_require_initialized_raises_for_missing_value() -> None:
    with pytest.raises(RuntimeError, match="missing"):
        require_initialized(None, "missing")
```

- [ ] **Step 5: Run the new runtime-layer test file**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/bootstrap_context.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: add runtime bootstrap context"
```

## Chunk 2: Layer-Owned Lifecycle Modules

### Task 2: Move infrastructure lifecycle ownership to the layer packages

**Files:**
- Create: `backend/src/magi/config/lifecycle.py`
- Create: `backend/src/magi/events/lifecycle.py`
- Create: `backend/src/magi/plugins/lifecycle.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write the failing ownership test for infrastructure layers**

```python
from magi.config.lifecycle import ConfigurationModule
from magi.events.lifecycle import MessageBusModule
from magi.plugins.lifecycle import PluginSystemModule


def test_infrastructure_and_platform_layers_own_their_lifecycle_modules() -> None:
    assert ConfigurationModule.__module__ == "magi.config.lifecycle"
    assert MessageBusModule.__module__ == "magi.events.lifecycle"
    assert PluginSystemModule.__module__ == "magi.plugins.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py::test_infrastructure_and_platform_layers_own_their_lifecycle_modules -v`
Expected: FAIL because the lifecycle modules still live in `magi.runtime.runtime_modules`.

- [ ] **Step 3: Create layer-owned lifecycle modules for config, events, and plugins**

```python
class ConfigurationModule(LifecycleModule):
    ...


class MessageBusModule(LifecycleModule):
    ...


class PluginSystemModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add an order smoke test for the first layers**

```python
from magi.runtime.bootstrap import build_runtime_modules
from magi.runtime.bootstrap_context import RuntimeBootstrapContext


def test_bootstrap_builds_expected_front_of_layer_order() -> None:
    modules = build_runtime_modules(RuntimeBootstrapContext())

    assert [module.name for module in modules[:4]] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
    ]
```

- [ ] **Step 5: Run the runtime lifecycle tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/config/lifecycle.py backend/src/magi/events/lifecycle.py backend/src/magi/plugins/lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move infra lifecycle into layer packages"
```

### Task 3: Move capability and memory-stack lifecycle ownership to the layer packages

**Files:**
- Create: `backend/src/magi/llm/lifecycle.py`
- Create: `backend/src/magi/tools/lifecycle.py`
- Create: `backend/src/magi/memory/lifecycle.py`
- Create: `backend/src/magi/personality/lifecycle.py`
- Create: `backend/src/magi/context/lifecycle.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write the failing ownership test for capability and memory layers**

```python
from magi.context.lifecycle import ContextModule
from magi.llm.lifecycle import LLMRuntimeModule
from magi.memory.lifecycle import MemoryStoreModule
from magi.personality.lifecycle import PersonalityModule
from magi.tools.lifecycle import ToolsModule


def test_capability_and_memory_layers_own_their_lifecycle_modules() -> None:
    assert LLMRuntimeModule.__module__ == "magi.llm.lifecycle"
    assert ToolsModule.__module__ == "magi.tools.lifecycle"
    assert MemoryStoreModule.__module__ == "magi.memory.lifecycle"
    assert PersonalityModule.__module__ == "magi.personality.lifecycle"
    assert ContextModule.__module__ == "magi.context.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py::test_capability_and_memory_layers_own_their_lifecycle_modules -v`
Expected: FAIL because these modules still live in `magi.runtime.runtime_modules`.

- [ ] **Step 3: Create the layer-owned lifecycle modules without changing behavior**

```python
class LLMRuntimeModule(LifecycleModule):
    ...


class MemoryStoreModule(LifecycleModule):
    ...


class PersonalityModule(LifecycleModule):
    ...


class ContextModule(LifecycleModule):
    ...


class ToolsModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add an order regression test through the context layer**

```python
assert [module.name for module in modules[:10]] == [
    "runtime_core_dependencies",
    "runtime_configuration",
    "runtime_message_bus",
    "runtime_plugin_system",
    "runtime_llm",
    "runtime_memory",
    "runtime_tools",
    "runtime_personality",
    "runtime_sensor_executor",
    "runtime_context",
]
```

- [ ] **Step 5: Run the runtime lifecycle tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/llm/lifecycle.py backend/src/magi/tools/lifecycle.py backend/src/magi/memory/lifecycle.py backend/src/magi/personality/lifecycle.py backend/src/magi/context/lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move capability lifecycle into owning layers"
```

### Task 4: Move runtime-domain lifecycle ownership to awareness, agent, timeline, and scheduler

**Files:**
- Create: `backend/src/magi/awareness/lifecycle.py`
- Create: `backend/src/magi/agent/lifecycle.py`
- Create: `backend/src/magi/timeline/lifecycle.py`
- Create: `backend/src/magi/scheduler/lifecycle.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write the failing ownership test for the runtime-domain layers**

```python
from magi.agent.lifecycle import AgentRuntimeModule
from magi.awareness.lifecycle import SensorExecutorModule
from magi.scheduler.lifecycle import SchedulerModule
from magi.timeline.lifecycle import TimelineModule


def test_runtime_domain_layers_own_their_lifecycle_modules() -> None:
    assert SensorExecutorModule.__module__ == "magi.awareness.lifecycle"
    assert AgentRuntimeModule.__module__ == "magi.agent.lifecycle"
    assert TimelineModule.__module__ == "magi.timeline.lifecycle"
    assert SchedulerModule.__module__ == "magi.scheduler.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py::test_runtime_domain_layers_own_their_lifecycle_modules -v`
Expected: FAIL because these modules still live in `magi.runtime.runtime_modules`.

- [ ] **Step 3: Create layer-owned lifecycle modules for awareness, agent, timeline, and scheduler**

```python
class SensorExecutorModule(LifecycleModule):
    ...


class AgentRuntimeModule(LifecycleModule):
    ...


class TimelineModule(LifecycleModule):
    ...


class SchedulerModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add a full-order regression test**

```python
def test_bootstrap_builds_expected_layer_order() -> None:
    modules = build_runtime_modules(RuntimeBootstrapContext())

    assert [module.name for module in modules] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
        "runtime_llm",
        "runtime_memory",
        "runtime_tools",
        "runtime_personality",
        "runtime_sensor_executor",
        "runtime_context",
        "runtime_agent_core",
        "runtime_timeline",
        "runtime_scheduler",
        "runtime_exports",
        "runtime_other_dependencies",
    ]
```

- [ ] **Step 5: Run the runtime lifecycle tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/awareness/lifecycle.py backend/src/magi/agent/lifecycle.py backend/src/magi/timeline/lifecycle.py backend/src/magi/scheduler/lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move runtime lifecycle into owning layers"
```

## Chunk 3: Thin Bootstrap Cutover

### Task 5: Rewrite `runtime/bootstrap.py` into a thin composition root

**Files:**
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: `backend/tests/runtime/test_bootstrap_llm_selection.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write the failing thin-bootstrap test**

```python
import magi.runtime.bootstrap as bootstrap


def test_bootstrap_uses_layer_owned_lifecycle_modules() -> None:
    assert bootstrap.RuntimeBootstrapContext.__module__ == "magi.runtime.bootstrap_context"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py::test_bootstrap_uses_layer_owned_lifecycle_modules -v`
Expected: FAIL because bootstrap still imports from `magi.runtime.runtime_modules`.

- [ ] **Step 3: Rewrite bootstrap to collect modules from the owning layers**

```python
def build_runtime_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    return [
        CoreDependenciesModule(context),
        ConfigurationModule(context),
        MessageBusModule(context),
        PluginSystemModule(context),
        ...
    ]
```

- [ ] **Step 4: Keep runtime entrypoints stable while moving imports**

```python
from .bootstrap_context import RuntimeBootstrapContext
```

- [ ] **Step 5: Run focused runtime regression tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py tests/runtime/test_bootstrap_llm_selection.py tests/runtime/test_lifecycle_orchestrator.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/bootstrap.py backend/src/magi/runtime/bootstrap_context.py backend/tests/runtime/test_layer_lifecycle_modules.py backend/tests/runtime/test_bootstrap_llm_selection.py
git commit -m "refactor: thin runtime bootstrap"
```

### Task 6: Delete `runtime/runtime_modules.py` and prove startup still works

**Files:**
- Delete: `backend/src/magi/runtime/runtime_modules.py`
- Test: `backend/tests/runtime/test_layer_lifecycle_modules.py`
- Test: `backend/tests/runtime/test_lifecycle_orchestrator.py`
- Test: `backend/tests/api/test_backend_app_websocket_bridge.py`

- [ ] **Step 1: Delete the monolithic runtime bootstrap file**

```bash
git rm /Users/asuka/code/magi/backend/src/magi/runtime/runtime_modules.py
```

- [ ] **Step 2: Run runtime-focused regression tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py tests/runtime/test_lifecycle_orchestrator.py -v`
Expected: PASS

- [ ] **Step 3: Run backend app startup wiring regression**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/api/test_backend_app_websocket_bridge.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/runtime/test_layer_lifecycle_modules.py
git rm backend/src/magi/runtime/runtime_modules.py
git commit -m "refactor: remove monolithic runtime modules"
```

## Notes

- This plan intentionally does **not** include A2 scheduler ownership changes. `SchedulerModule` may temporarily stay behaviorally unchanged while its ownership moves into `scheduler/lifecycle.py`.
- This plan intentionally does **not** include A3 transport-layer migration.
- This plan intentionally does **not** remove runtime global fallbacks yet; that belongs to A8.
- The success condition for A1 is structural ownership change: lifecycle logic lives in the owning layer, while `runtime/bootstrap.py` becomes thin.

## Verification Handoff

After the last task, re-run the focused regression set once more:

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_layer_lifecycle_modules.py tests/runtime/test_bootstrap_llm_selection.py tests/runtime/test_lifecycle_orchestrator.py tests/api/test_backend_app_websocket_bridge.py -v`
Expected: PASS

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a1-runtime-modules-decomposition.md`. Ready to execute?
