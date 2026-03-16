# A2 Scheduler Engine Decoupling Implementation Plan

**Status:** Completed on 2026-03-16

**Completed commits:**
- `e375999` `refactor: reduce scheduler to engine layer`
- `c91798f` `refactor: move agent schedule registration to agent layer`
- `4b34731` `refactor: move action schedule registration to awareness`
- `110f777` `refactor: move timeline schedule registration to timeline`
- `41a997c` `refactor: finalize scheduler engine decoupling`

**Implementation result:** `scheduler/` now only owns engine startup, persistence, runtime service exposure, and generic scheduling contracts. Domain-owned registration has moved to the owning layers: `agent` owns `AGENT_TASK`, `awareness` owns `ACTION_DISPATCH`, and `timeline` owns timeline sync registration plus schedule refresh.

**As-built deltas from the original plan:**
- `backend/src/magi/agent/scheduler_contrib.py` did not need a functional change. Ownership moved by introducing `AgentScheduleRegistrationModule` in `agent/lifecycle.py`, while the existing contributor implementation remained valid.
- `backend/src/magi/core/runtime/action_scheduler_contrib.py` also did not need a functional change. Ownership moved by introducing `ActionScheduleRegistrationModule` in `awareness/lifecycle.py`.
- `backend/tests/scheduler/test_scheduler_bootstrap.py` was deleted and replaced by owner-specific lifecycle coverage in `backend/tests/timeline/test_timeline_scheduler_lifecycle.py`, together with the existing API regression coverage in `backend/tests/api/test_timeline_api.py`.
- `backend/tests/scheduler/test_scheduler_service.py` did not require code changes during the final cleanup because it already covered engine-level scheduler behavior and remained valid as regression coverage.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `scheduler/` to a pure engine layer that only starts the scheduler service and exposes engine-level contracts, while timeline, agent, and action layers register their own handlers and schedules from their owning packages.

**Architecture:** `scheduler/` should own APScheduler, persistence, and generic schedule contracts only. Domain-specific scheduling policy must move back into the owning layers: timeline owns timeline sync registration and refresh, agent owns `AGENT_TASK` registration, and the sensors/actions layer owns `ACTION_DISPATCH` registration. The bootstrap builder may still sequence these lifecycle modules, but `SchedulerModule` must stop constructing domain contributors directly.

**Tech Stack:** Python 3.10+, pytest, APScheduler, dependency-injector, Magi layered lifecycle modules

---

## File Structure

### Scheduler engine layer

- Modify: `backend/src/magi/scheduler/lifecycle.py`
  Keep only scheduler engine startup/shutdown and engine-level runtime exposure.
- Modify: `backend/src/magi/scheduler/runtime.py`
  Remove bootstrap-coupled refresh flow and converge to engine-only runtime state.
- Modify: `backend/src/magi/scheduler/__init__.py`
  Stop exporting legacy bootstrap APIs after cutover.
- Delete: `backend/src/magi/scheduler/bootstrap.py`
  Remove the legacy scheduler bootstrap helper once contributor-owned registration replaces it.
- Modify: `backend/tests/scheduler/test_scheduler_runtime.py`
  Follow the engine-only runtime surface.
- Delete or rewrite: `backend/tests/scheduler/test_scheduler_bootstrap.py`
  Replace legacy bootstrap tests with contributor-owned integration tests.

### Agent-owned scheduling

- Modify: `backend/src/magi/agent/lifecycle.py`
  Split agent runtime startup from agent schedule registration.
- Modify: `backend/src/magi/agent/scheduler_contrib.py`
  Keep contributor logic focused on agent-owned registration only.
- Create: `backend/tests/agent/test_agent_scheduler_lifecycle.py`
  Verify agent-owned lifecycle registers `AGENT_TASK` after scheduler startup.

### Timeline-owned scheduling

- Modify: `backend/src/magi/timeline/lifecycle.py`
  Add timeline-owned scheduler registration lifecycle and remove scheduler-owned construction.
- Modify: `backend/src/magi/timeline/scheduler_contrib.py`
  Remove global ownership from scheduler layer and keep runtime access local to timeline.
- Modify: `backend/src/magi/api/routers/timeline.py`
  Continue using timeline-owned runtime access, not scheduler bootstrap.
- Modify: `backend/src/magi/plugins/manager.py`
  Refresh timeline schedules via a timeline-owned entrypoint instead of `scheduler.runtime`.
- Create: `backend/tests/timeline/test_timeline_scheduler_lifecycle.py`
  Verify timeline registers handlers and schedules from the timeline layer.

### Action-owned scheduling

- Modify: `backend/src/magi/awareness/lifecycle.py`
  Add action scheduling registration lifecycle owned by the sensors/actions layer.
- Modify: `backend/src/magi/core/runtime/action_scheduler_contrib.py`
  Keep contributor focused on action-owned handler registration.
- Create: `backend/tests/awareness/test_action_scheduler_lifecycle.py`
  Verify action-owned lifecycle registers `ACTION_DISPATCH`.

### Bootstrap assembly

- Modify: `backend/src/magi/bootstrap/builder.py`
  Insert owner-specific scheduling lifecycle modules after scheduler engine startup.
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`
  Update expected lifecycle order to include engine module plus owner-specific scheduling modules.

### Documentation

- Reference only: `docs/issues/layered-architecture-remediation-checklist.md`
  Mark A2 progress after implementation lands.

## Chunk 1: Scheduler Engine Only

### Task 1: Prove scheduler lifecycle still owns domain registration

**Files:**
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`
- Modify: `backend/tests/scheduler/test_scheduler_runtime.py`

- [ ] **Step 1: Write the failing scheduler-ownership test**

```python
def test_scheduler_module_does_not_import_domain_contributors() -> None:
    from magi.scheduler import lifecycle as scheduler_lifecycle

    source = Path(scheduler_lifecycle.__file__).read_text(encoding="utf-8")

    assert "TimelineSchedulerContrib" not in source
    assert "AgentSchedulerContrib" not in source
    assert "ActionSchedulerContrib" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/runtime/test_layer_lifecycle_modules.py::test_scheduler_module_does_not_import_domain_contributors -q`
Expected: FAIL because `scheduler/lifecycle.py` still imports all three domain contributors.

- [ ] **Step 3: Add a failing runtime test for engine-only scheduler globals**

```python
def test_scheduler_runtime_tracks_service_without_bootstrap() -> None:
    from magi.scheduler.runtime import get_scheduler_service, set_scheduler_runtime

    service = object()
    set_scheduler_runtime(service)

    assert get_scheduler_service() is service
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/scheduler/test_scheduler_runtime.py::test_scheduler_runtime_tracks_service_without_bootstrap -q`
Expected: FAIL because `set_scheduler_runtime()` still requires `bootstrap`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/runtime/test_layer_lifecycle_modules.py backend/tests/scheduler/test_scheduler_runtime.py
git commit -m "test: cover scheduler engine ownership"
```

### Task 2: Reduce `SchedulerModule` to scheduler engine startup/shutdown only

**Files:**
- Modify: `backend/src/magi/scheduler/lifecycle.py`
- Modify: `backend/src/magi/scheduler/runtime.py`
- Modify: `backend/src/magi/scheduler/__init__.py`
- Delete: `backend/src/magi/scheduler/bootstrap.py`
- Modify: `backend/tests/scheduler/test_scheduler_runtime.py`

- [ ] **Step 1: Remove contributor construction from `SchedulerModule`**

```python
class SchedulerModule(LifecycleModule):
    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )
        await scheduler_service.start()
        set_scheduler_runtime(scheduler_service)
        self._context.scheduler.scheduler_service = scheduler_service
```

- [ ] **Step 2: Simplify scheduler runtime globals**

```python
def set_scheduler_runtime(service: SchedulerService | None) -> None:
    global _scheduler_service
    _scheduler_service = service
```

- [ ] **Step 3: Delete legacy `SchedulerBootstrap` and its exports**

```python
__all__ = [
    "ScheduleDefinition",
    "SchedulerService",
    "get_scheduler_service",
    "request_scheduler_refresh",
]
```

- [ ] **Step 4: Rewrite runtime tests for engine-only behavior**

```python
def test_request_scheduler_refresh_is_timeline_owned() -> None:
    with pytest.raises(AttributeError):
        import magi.scheduler.runtime as runtime
        getattr(runtime, "request_scheduler_refresh")
```

- [ ] **Step 5: Run focused scheduler tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/scheduler/test_scheduler_runtime.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/scheduler/lifecycle.py backend/src/magi/scheduler/runtime.py backend/src/magi/scheduler/__init__.py backend/tests/scheduler/test_scheduler_runtime.py backend/tests/runtime/test_layer_lifecycle_modules.py
git rm backend/src/magi/scheduler/bootstrap.py
git commit -m "refactor: reduce scheduler to engine layer"
```

## Chunk 2: Owner-Specific Registration

### Task 3: Move agent schedule registration into the agent layer

**Files:**
- Modify: `backend/src/magi/agent/lifecycle.py`
- Modify: `backend/src/magi/agent/scheduler_contrib.py`
- Create: `backend/tests/agent/test_agent_scheduler_lifecycle.py`
- Modify: `backend/src/magi/bootstrap/builder.py`

- [ ] **Step 1: Write the failing ownership test**

```python
def test_agent_schedule_registration_module_lives_in_agent_layer() -> None:
    from magi.agent.lifecycle import AgentScheduleRegistrationModule

    assert AgentScheduleRegistrationModule.__module__ == "magi.agent.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/agent/test_agent_scheduler_lifecycle.py::test_agent_schedule_registration_module_lives_in_agent_layer -q`
Expected: FAIL because there is no agent-owned scheduler lifecycle module yet.

- [ ] **Step 3: Add an agent-owned lifecycle module**

```python
class AgentScheduleRegistrationModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_scheduler",
            dependencies=("runtime_agent_core", "runtime_scheduler"),
        )

    async def init(self) -> None:
        scheduler = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        manager = require_initialized(self._context.agent_runtime.task_agent_manager, "task agent manager")
        self._contrib = AgentSchedulerContrib(task_agent_manager=manager)
        await self._contrib.register_schedules(scheduler)
```

- [ ] **Step 4: Insert agent scheduler registration into bootstrap ordering**

```python
SchedulerModule(context),
AgentScheduleRegistrationModule(context),
```

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/agent/test_agent_scheduler_lifecycle.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/agent/lifecycle.py backend/src/magi/agent/scheduler_contrib.py backend/src/magi/bootstrap/builder.py backend/tests/agent/test_agent_scheduler_lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move agent schedule registration to agent layer"
```

### Task 4: Move action schedule registration into the sensors/actions layer

**Files:**
- Modify: `backend/src/magi/awareness/lifecycle.py`
- Modify: `backend/src/magi/core/runtime/action_scheduler_contrib.py`
- Modify: `backend/src/magi/bootstrap/builder.py`
- Create: `backend/tests/awareness/test_action_scheduler_lifecycle.py`

- [ ] **Step 1: Write the failing ownership test**

```python
def test_action_schedule_registration_module_lives_in_awareness_layer() -> None:
    from magi.awareness.lifecycle import ActionScheduleRegistrationModule

    assert ActionScheduleRegistrationModule.__module__ == "magi.awareness.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/awareness/test_action_scheduler_lifecycle.py::test_action_schedule_registration_module_lives_in_awareness_layer -q`
Expected: FAIL because the awareness-owned registration module does not exist yet.

- [ ] **Step 3: Add an awareness-owned action registration module**

```python
class ActionScheduleRegistrationModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_action_scheduler",
            dependencies=("runtime_sensor_executor", "runtime_scheduler"),
        )
```

- [ ] **Step 4: Update bootstrap order**

```python
SchedulerModule(context),
AgentScheduleRegistrationModule(context),
ActionScheduleRegistrationModule(context),
```

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/awareness/test_action_scheduler_lifecycle.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/awareness/lifecycle.py backend/src/magi/core/runtime/action_scheduler_contrib.py backend/src/magi/bootstrap/builder.py backend/tests/awareness/test_action_scheduler_lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move action schedule registration to awareness"
```

### Task 5: Move timeline schedule registration and refresh into the timeline layer

**Files:**
- Modify: `backend/src/magi/timeline/lifecycle.py`
- Modify: `backend/src/magi/timeline/scheduler_contrib.py`
- Modify: `backend/src/magi/plugins/manager.py`
- Modify: `backend/src/magi/api/routers/timeline.py`
- Modify: `backend/src/magi/bootstrap/builder.py`
- Create: `backend/tests/timeline/test_timeline_scheduler_lifecycle.py`
- Modify: `backend/tests/scheduler/test_scheduler_bootstrap.py`

- [ ] **Step 1: Write the failing ownership test**

```python
def test_timeline_schedule_registration_module_lives_in_timeline_layer() -> None:
    from magi.timeline.lifecycle import TimelineScheduleRegistrationModule

    assert TimelineScheduleRegistrationModule.__module__ == "magi.timeline.lifecycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/timeline/test_timeline_scheduler_lifecycle.py::test_timeline_schedule_registration_module_lives_in_timeline_layer -q`
Expected: FAIL because timeline registration still happens inside `scheduler/lifecycle.py`.

- [ ] **Step 3: Add a timeline-owned registration lifecycle module**

```python
class TimelineScheduleRegistrationModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_timeline_scheduler",
            dependencies=("runtime_timeline", "runtime_plugin_system", "runtime_scheduler"),
        )
```

- [ ] **Step 4: Move refresh access into timeline-owned runtime helpers**

```python
def request_timeline_schedule_refresh() -> None:
    contrib = get_timeline_scheduler_contrib()
    if contrib is None:
        return
    ...
```

- [ ] **Step 5: Update plugin manager to call timeline-owned refresh**

```python
from ..timeline.scheduler_contrib import request_timeline_schedule_refresh
```

- [ ] **Step 6: Replace legacy scheduler bootstrap tests with timeline-owned lifecycle tests**

```python
assert await timeline_schedule_module.queue_manual_sync("pull_history")
```

- [ ] **Step 7: Run focused tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/timeline/test_timeline_scheduler_lifecycle.py tests/api/test_timeline_api.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/timeline/lifecycle.py backend/src/magi/timeline/scheduler_contrib.py backend/src/magi/plugins/manager.py backend/src/magi/api/routers/timeline.py backend/src/magi/bootstrap/builder.py backend/tests/timeline/test_timeline_scheduler_lifecycle.py backend/tests/api/test_timeline_api.py backend/tests/runtime/test_layer_lifecycle_modules.py backend/tests/scheduler/test_scheduler_bootstrap.py
git commit -m "refactor: move timeline schedule registration to timeline"
```

## Chunk 3: Final Scheduler Cleanup

### Task 6: Remove legacy scheduler bootstrap references and stabilize lifecycle order

**Files:**
- Modify: `backend/src/magi/bootstrap/builder.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`
- Modify: `backend/tests/scheduler/test_scheduler_service.py`
- Modify: `backend/src/magi/scheduler/__init__.py`

- [ ] **Step 1: Update expected lifecycle order**

```python
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
    "runtime_agent_scheduler",
    "runtime_action_scheduler",
    "runtime_timeline_scheduler",
    "runtime_exports",
    "runtime_other_dependencies",
]
```

- [ ] **Step 2: Remove legacy scheduler bootstrap exports**

```python
__all__ = [
    "ScheduleDefinition",
    "SchedulerService",
    "get_scheduler_service",
]
```

- [ ] **Step 3: Run scheduler-focused regression suite**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/scheduler/test_scheduler_service.py tests/scheduler/test_scheduler_runtime.py tests/runtime/test_layer_lifecycle_modules.py tests/api/test_timeline_api.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/bootstrap/builder.py backend/src/magi/scheduler/__init__.py backend/tests/runtime/test_layer_lifecycle_modules.py backend/tests/scheduler/test_scheduler_service.py backend/tests/scheduler/test_scheduler_runtime.py backend/tests/api/test_timeline_api.py
git commit -m "refactor: finalize scheduler engine decoupling"
```

## Notes

- This plan intentionally does **not** include A3 transport-layer migration.
- This plan intentionally does **not** include A4 API-side lifecycle cleanup beyond timeline/manual sync callsites touched by scheduler decoupling.
- This plan intentionally does **not** include A6 action emitter renaming; the contributor can continue using current action executor naming until that refactor lands.
- The success condition for A2 is structural: `scheduler/` starts and exposes the engine only, while timeline, agent, and action layers own their schedule registration and refresh behavior.

## Verification Handoff

After the last task, run the full scheduler-adjacent regression set once more:

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/runtime/test_layer_lifecycle_modules.py tests/scheduler/test_scheduler_runtime.py tests/scheduler/test_scheduler_service.py tests/timeline/test_timeline_scheduler_lifecycle.py tests/api/test_timeline_api.py tests/agent/test_agent_scheduler_lifecycle.py tests/awareness/test_action_scheduler_lifecycle.py -q`
Expected: PASS

**Actual verification result:** PASS (`37 passed`).

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a2-scheduler-engine-decoupling.md`.
