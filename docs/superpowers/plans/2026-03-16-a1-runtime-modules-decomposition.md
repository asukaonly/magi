# A1 Runtime Modules Decomposition Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `backend/src/magi/runtime/runtime_modules.py` as the cross-layer bootstrap hub and replace it with a smaller, layer-aligned runtime module package with narrower shared state.

**Architecture:** Split the current monolithic runtime bootstrap file into a dedicated `runtime/modules/` package, group lifecycle modules by responsibility, and replace the flat bootstrap state table with typed state slices. Keep runtime behavior stable while changing only structure and wiring, so A2 scheduler decoupling and later L13/L14 migration can build on a cleaner bootstrap boundary.

**Tech Stack:** Python 3.10+, pytest, dependency-injector, Magi runtime lifecycle modules

---

## File Structure

### New runtime module package

- Create: `backend/src/magi/runtime/modules/__init__.py`
  Export the new runtime module builder and shared state entry points.
- Create: `backend/src/magi/runtime/modules/state.py`
  Move `RuntimeInitializationDeferred`, `_require(...)`, and bootstrap state into a typed, slice-based structure.
- Create: `backend/src/magi/runtime/modules/infrastructure.py`
  Own `CoreDependenciesModule`, `ConfigurationModule`, and `MessageBusModule`.
- Create: `backend/src/magi/runtime/modules/capabilities.py`
  Own `PluginSystemModule`, `LLMRuntimeModule`, and `ToolsModule`.
- Create: `backend/src/magi/runtime/modules/memory_stack.py`
  Own `MemoryStoreModule`, `PersonalityModule`, and `ContextModule`.
- Create: `backend/src/magi/runtime/modules/runtime_stack.py`
  Own `SensorExecutorModule`, `AgentRuntimeModule`, `TimelineModule`, `SchedulerModule`, `RuntimeExportsModule`, and the maintenance module.
- Create: `backend/src/magi/runtime/modules/builders.py`
  Own `build_runtime_modules(...)` and the ordered lifecycle assembly.

### Existing runtime entrypoints

- Modify: `backend/src/magi/runtime/bootstrap.py`
  Import `RuntimeBootstrapState` and `build_runtime_modules` from the new package.
- Modify: `backend/src/magi/runtime/__init__.py`
  Only if export paths need cleanup after the move.
- Delete: `backend/src/magi/runtime/runtime_modules.py`
  Remove the monolithic bootstrap file after the new package is fully wired.

### Tests

- Create: `backend/tests/runtime/test_runtime_module_builder.py`
  Cover package existence, module ownership, state slicing, and builder order.
- Modify: `backend/tests/runtime/test_bootstrap_llm_selection.py`
  Only if import paths or bootstrap assertions need to follow the new builder/state location.
- Re-run: `backend/tests/runtime/test_lifecycle_orchestrator.py`
  Guard the lifecycle startup/shutdown contract.
- Re-run: `backend/tests/api/test_backend_app_websocket_bridge.py`
  Guard backend app startup wiring against bootstrap regressions.

### Documentation

- Reference only: `docs/issues/layered-architecture-remediation-checklist.md`
  Track A1 completion status once implementation lands.

## Chunk 1: Bootstrap Package Skeleton

### Task 1: Introduce the `runtime/modules` package and move shared bootstrap contracts

**Files:**
- Create: `backend/src/magi/runtime/modules/__init__.py`
- Create: `backend/src/magi/runtime/modules/state.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`

- [ ] **Step 1: Write the failing package/state test**

```python
from magi.runtime.modules import RuntimeBootstrapState


def test_runtime_modules_package_exports_state_entrypoint() -> None:
    state = RuntimeBootstrapState()

    assert hasattr(state, "core")
    assert hasattr(state, "llm")
    assert hasattr(state, "memory")
    assert hasattr(state, "runtime")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_runtime_modules_package_exports_state_entrypoint -v`
Expected: FAIL because `magi.runtime.modules` does not exist yet.

- [ ] **Step 3: Create the package and slice-based bootstrap state**

```python
@dataclass
class CoreModuleState:
    config: AppConfig | None = None
    runtime_paths: RuntimePaths | None = None
    db_initializer: DatabaseInitializer | None = None


@dataclass
class RuntimeBootstrapState:
    core: CoreModuleState = field(default_factory=CoreModuleState)
    llm: LLMModuleState = field(default_factory=LLMModuleState)
    memory: MemoryModuleState = field(default_factory=MemoryModuleState)
    runtime: RuntimeModuleState = field(default_factory=RuntimeModuleState)
```

- [ ] **Step 4: Export the new state entrypoint**

```python
from .state import RuntimeBootstrapState, RuntimeInitializationDeferred
```

- [ ] **Step 5: Run the focused test to verify it passes**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_runtime_modules_package_exports_state_entrypoint -v`
Expected: PASS

- [ ] **Step 6: Add a regression test for `_require(...)` and slice defaults**

```python
import pytest

from magi.runtime.modules.state import RuntimeBootstrapState, _require


def test_runtime_bootstrap_state_slice_defaults_start_empty() -> None:
    state = RuntimeBootstrapState()

    assert state.core.config is None
    assert state.runtime.agent_runtime is None


def test_require_raises_for_missing_value() -> None:
    with pytest.raises(RuntimeError, match="missing"):
        _require(None, "missing")
```

- [ ] **Step 7: Run the new runtime builder test file**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/runtime/modules/__init__.py backend/src/magi/runtime/modules/state.py backend/tests/runtime/test_runtime_module_builder.py
git commit -m "refactor: add runtime modules package"
```

### Task 2: Move infrastructure lifecycle modules out of `runtime_modules.py`

**Files:**
- Create: `backend/src/magi/runtime/modules/infrastructure.py`
- Modify: `backend/src/magi/runtime/modules/builders.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`

- [ ] **Step 1: Write the failing ownership test**

```python
from magi.runtime.modules.infrastructure import CoreDependenciesModule, ConfigurationModule, MessageBusModule


def test_infrastructure_modules_live_in_dedicated_runtime_package() -> None:
    assert CoreDependenciesModule.__module__ == "magi.runtime.modules.infrastructure"
    assert ConfigurationModule.__module__ == "magi.runtime.modules.infrastructure"
    assert MessageBusModule.__module__ == "magi.runtime.modules.infrastructure"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_infrastructure_modules_live_in_dedicated_runtime_package -v`
Expected: FAIL because `infrastructure.py` does not exist yet.

- [ ] **Step 3: Move the infrastructure modules into `infrastructure.py`**

```python
class CoreDependenciesModule(LifecycleModule):
    ...


class ConfigurationModule(LifecycleModule):
    ...


class MessageBusModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add a builder smoke test for the leading module order**

```python
from magi.runtime.modules import RuntimeBootstrapState
from magi.runtime.modules.builders import build_runtime_modules


def test_runtime_module_builder_starts_with_infrastructure_layers() -> None:
    modules = build_runtime_modules(RuntimeBootstrapState())
    names = [module.name for module in modules[:3]]

    assert names == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
    ]
```

- [ ] **Step 5: Run the focused builder tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/modules/infrastructure.py backend/src/magi/runtime/modules/builders.py backend/tests/runtime/test_runtime_module_builder.py
git commit -m "refactor: extract runtime infrastructure modules"
```

## Chunk 2: Capability And Memory Stack Extraction

### Task 3: Move plugin, LLM, and tools lifecycle modules into a dedicated capability file

**Files:**
- Create: `backend/src/magi/runtime/modules/capabilities.py`
- Modify: `backend/src/magi/runtime/modules/builders.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`

- [ ] **Step 1: Write the failing capability-module ownership test**

```python
from magi.runtime.modules.capabilities import PluginSystemModule, LLMRuntimeModule, ToolsModule


def test_capability_modules_live_in_dedicated_runtime_package() -> None:
    assert PluginSystemModule.__module__ == "magi.runtime.modules.capabilities"
    assert LLMRuntimeModule.__module__ == "magi.runtime.modules.capabilities"
    assert ToolsModule.__module__ == "magi.runtime.modules.capabilities"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_capability_modules_live_in_dedicated_runtime_package -v`
Expected: FAIL because `capabilities.py` does not exist yet.

- [ ] **Step 3: Move the capability modules without changing behavior**

```python
class PluginSystemModule(LifecycleModule):
    ...


class LLMRuntimeModule(LifecycleModule):
    ...


class ToolsModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Extend the builder-order test through the tools layer**

```python
assert [module.name for module in modules[:6]] == [
    "runtime_core_dependencies",
    "runtime_configuration",
    "runtime_message_bus",
    "runtime_plugin_system",
    "runtime_llm",
    "runtime_memory",
]
```

- [ ] **Step 5: Run the runtime builder tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/modules/capabilities.py backend/src/magi/runtime/modules/builders.py backend/tests/runtime/test_runtime_module_builder.py
git commit -m "refactor: extract runtime capability modules"
```

### Task 4: Move memory, personality, and context lifecycle modules into a dedicated memory-stack file

**Files:**
- Create: `backend/src/magi/runtime/modules/memory_stack.py`
- Modify: `backend/src/magi/runtime/modules/builders.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`

- [ ] **Step 1: Write the failing memory-stack ownership test**

```python
from magi.runtime.modules.memory_stack import MemoryStoreModule, PersonalityModule, ContextModule


def test_memory_stack_modules_live_in_dedicated_runtime_package() -> None:
    assert MemoryStoreModule.__module__ == "magi.runtime.modules.memory_stack"
    assert PersonalityModule.__module__ == "magi.runtime.modules.memory_stack"
    assert ContextModule.__module__ == "magi.runtime.modules.memory_stack"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_memory_stack_modules_live_in_dedicated_runtime_package -v`
Expected: FAIL because `memory_stack.py` does not exist yet.

- [ ] **Step 3: Move the three modules and update them to use the new state slices**

```python
class MemoryStoreModule(LifecycleModule):
    ...


class PersonalityModule(LifecycleModule):
    ...


class ContextModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add a regression test for builder ordering through context**

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

- [ ] **Step 5: Run the runtime builder tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/modules/memory_stack.py backend/src/magi/runtime/modules/builders.py backend/tests/runtime/test_runtime_module_builder.py
git commit -m "refactor: extract runtime memory stack modules"
```

## Chunk 3: Runtime Stack Cutover

### Task 5: Move agent, timeline, scheduler, exports, and maintenance lifecycle modules into a runtime-stack file

**Files:**
- Create: `backend/src/magi/runtime/modules/runtime_stack.py`
- Modify: `backend/src/magi/runtime/modules/builders.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`

- [ ] **Step 1: Write the failing runtime-stack ownership test**

```python
from magi.runtime.modules.runtime_stack import (
    AgentRuntimeModule,
    RuntimeExportsModule,
    SchedulerModule,
    SensorExecutorModule,
    TimelineModule,
)


def test_runtime_stack_modules_live_in_dedicated_runtime_package() -> None:
    assert SensorExecutorModule.__module__ == "magi.runtime.modules.runtime_stack"
    assert AgentRuntimeModule.__module__ == "magi.runtime.modules.runtime_stack"
    assert TimelineModule.__module__ == "magi.runtime.modules.runtime_stack"
    assert SchedulerModule.__module__ == "magi.runtime.modules.runtime_stack"
    assert RuntimeExportsModule.__module__ == "magi.runtime.modules.runtime_stack"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_runtime_stack_modules_live_in_dedicated_runtime_package -v`
Expected: FAIL because `runtime_stack.py` does not exist yet.

- [ ] **Step 3: Move the runtime stack modules and update them to use the sliced state**

```python
class SensorExecutorModule(LifecycleModule):
    ...


class AgentRuntimeModule(LifecycleModule):
    ...


class TimelineModule(LifecycleModule):
    ...


class SchedulerModule(LifecycleModule):
    ...


class RuntimeExportsModule(LifecycleModule):
    ...


class OtherDependenciesModule(LifecycleModule):
    ...
```

- [ ] **Step 4: Add a full builder-order regression test**

```python
def test_runtime_module_builder_preserves_expected_order() -> None:
    modules = build_runtime_modules(RuntimeBootstrapState())

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

- [ ] **Step 5: Run the runtime builder tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/modules/runtime_stack.py backend/src/magi/runtime/modules/builders.py backend/tests/runtime/test_runtime_module_builder.py
git commit -m "refactor: extract runtime stack modules"
```

### Task 6: Cut bootstrap over to the new package and delete `runtime_modules.py`

**Files:**
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Delete: `backend/src/magi/runtime/runtime_modules.py`
- Modify: `backend/src/magi/runtime/modules/__init__.py`
- Test: `backend/tests/runtime/test_runtime_module_builder.py`
- Test: `backend/tests/runtime/test_bootstrap_llm_selection.py`
- Test: `backend/tests/runtime/test_lifecycle_orchestrator.py`
- Test: `backend/tests/api/test_backend_app_websocket_bridge.py`

- [ ] **Step 1: Write the failing bootstrap import-path test**

```python
import magi.runtime.bootstrap as bootstrap


def test_runtime_bootstrap_uses_new_runtime_modules_package() -> None:
    assert bootstrap.RuntimeBootstrapState.__module__ == "magi.runtime.modules.state"
    assert bootstrap.build_runtime_modules.__module__ == "magi.runtime.modules.builders"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py::test_runtime_bootstrap_uses_new_runtime_modules_package -v`
Expected: FAIL because bootstrap still imports from `magi.runtime.runtime_modules`.

- [ ] **Step 3: Switch bootstrap to the new package and delete the monolithic file**

```python
from .modules import RuntimeBootstrapState
from .modules.builders import build_runtime_modules
```

- [ ] **Step 4: Run focused runtime regression tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py tests/runtime/test_bootstrap_llm_selection.py tests/runtime/test_lifecycle_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Run backend-app startup wiring regression**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/api/test_backend_app_websocket_bridge.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/runtime/bootstrap.py backend/src/magi/runtime/modules backend/tests/runtime/test_runtime_module_builder.py backend/tests/runtime/test_bootstrap_llm_selection.py
git rm backend/src/magi/runtime/runtime_modules.py
git commit -m "refactor: remove monolithic runtime modules"
```

## Notes

- This plan intentionally does **not** fold in A2 scheduler ownership changes, A3 transport-layer migration, or A8 global fallback cleanup.
- If any task uncovers unavoidable overlap with A2 or A8, document the minimal overlap in the commit body instead of opportunistically expanding scope.
- The implementation should preserve runtime behavior; this phase is structural decomposition first.

## Verification Handoff

After the last task, re-run the focused runtime regression set once more:

Run: `cd /Users/asuka/code/magi/backend && pytest tests/runtime/test_runtime_module_builder.py tests/runtime/test_bootstrap_llm_selection.py tests/runtime/test_lifecycle_orchestrator.py tests/api/test_backend_app_websocket_bridge.py -v`
Expected: PASS

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a1-runtime-modules-decomposition.md`. Ready to execute?
