# A5 Skills Lifecycle Unification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the skills runtime so `skills/` owns one shared lifecycle and `agent/` consumes that shared runtime instead of constructing a private `SkillIndexer/SkillLoader/SkillExecutor` stack inside `ChatTaskAgent`.

**Architecture:** Move shared skills initialization out of `tools/lifecycle.py` into a dedicated `skills/lifecycle.py`, store the initialized runtime in bootstrap-owned state, and thread the shared `skill_executor` into chat-agent construction explicitly. A5 only removes duplicate runtime ownership; it does not redesign the skills API surface or the broader prompt/context boundary.

**Tech Stack:** Python 3.10+, FastAPI runtime bootstrap, dependency-injector bindings, pytest

---

## File Structure

### Skills Layer Ownership

- Create: `backend/src/magi/skills/lifecycle.py`
  Own the shared skills runtime lifecycle for `L7`.
- Modify: `backend/src/magi/bootstrap/context.py`
  Add a dedicated bootstrap state slice for shared skills runtime objects.
- Modify: `backend/src/magi/bootstrap/builder.py`
  Insert the new skills lifecycle module into bootstrap ordering.
- Modify: `backend/src/magi/tools/lifecycle.py`
  Remove shared skills initialization so `tools/` only owns tool-layer setup.

### Agent Runtime Consumption

- Modify: `backend/src/magi/agent/lifecycle.py`
  Pass the shared `skill_executor` from bootstrap state into the chat agent factory.
- Modify: `backend/src/magi/agent/task_agents/factory.py`
  Accept shared skills runtime dependencies explicitly.
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
  Remove private `SkillIndexer/SkillLoader/SkillExecutor` construction and use the injected shared executor.

### Runtime Exports

- Modify: `backend/src/magi/bootstrap/exports.py`
  Export skills bindings from bootstrap-owned skills state instead of re-reading them indirectly.

### Tests

- Create: `backend/tests/skills/test_skills_lifecycle.py`
  Verify `SkillsModule` initializes the shared runtime and stores it in bootstrap state.
- Create: `backend/tests/agent/test_chat_task_agent_skills_binding.py`
  Verify `ChatTaskAgent` uses an injected shared `skill_executor`.
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`
  Lock the new `runtime_skills` module ownership and lifecycle order.
- Modify: `backend/tests/api/test_skills_router.py`
  Keep the API-level shared skills flow green after the lifecycle ownership move.

## Chunk 1: Lock The New Ownership Boundary

### Task 1: Add failing tests for skills lifecycle ownership and chat-agent injection

**Files:**
- Create: `backend/tests/skills/test_skills_lifecycle.py`
- Create: `backend/tests/agent/test_chat_task_agent_skills_binding.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Write a failing lifecycle ownership test**

```python
from types import SimpleNamespace

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.skills.lifecycle import SkillsModule


async def test_skills_module_populates_shared_runtime(monkeypatch) -> None:
    context = RuntimeBootstrapContext()
    context.core.config = SimpleNamespace(features=SimpleNamespace(enable_skills=True))
    context.llm.llm_adapter = object()

    fake_indexer = object()
    fake_loader = object()
    fake_executor = object()

    monkeypatch.setattr("magi.skills.lifecycle.init_skills_module", lambda llm_adapter=None: None)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_indexer", lambda: fake_indexer)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_loader", lambda: fake_loader)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_executor", lambda: fake_executor)

    module = SkillsModule(context)
    await module.init()

    assert context.skills.skill_indexer is fake_indexer
    assert context.skills.skill_loader is fake_loader
    assert context.skills.skill_executor is fake_executor
```

- [ ] **Step 2: Write a failing chat-agent binding test**

```python
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent


def test_chat_task_agent_uses_injected_shared_skill_executor() -> None:
    shared_executor = object()

    agent = ChatTaskAgent(
        agent_id="chat-test",
        llm_adapter=None,
        skill_executor=shared_executor,
    )

    assert agent.function_calling_executor.skill_executor is shared_executor
```

- [ ] **Step 3: Extend runtime layer-order tests**

```python
assert [module.name for module in modules[:11]] == [
    "runtime_core_dependencies",
    "runtime_configuration",
    "runtime_message_bus",
    "runtime_plugin_system",
    "runtime_llm",
    "runtime_memory",
    "runtime_tools",
    "runtime_skills",
    "runtime_personality",
    "runtime_sensor_executor",
    "runtime_context",
]
```

```python
source = Path(magi.tools.lifecycle.__file__).read_text(encoding="utf-8")
assert "init_skills_module" not in source
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/skills/test_skills_lifecycle.py tests/agent/test_chat_task_agent_skills_binding.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: FAIL because there is no `SkillsModule`, bootstrap has no `skills` state slice, and `ChatTaskAgent` still builds a private skills runtime.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/skills/test_skills_lifecycle.py backend/tests/agent/test_chat_task_agent_skills_binding.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "test: cover shared skills lifecycle ownership"
```

## Chunk 2: Create A Shared Skills Lifecycle Module

### Task 2: Move shared skills initialization into `skills/`

**Files:**
- Create: `backend/src/magi/skills/lifecycle.py`
- Modify: `backend/src/magi/bootstrap/context.py`
- Modify: `backend/src/magi/bootstrap/builder.py`
- Modify: `backend/src/magi/tools/lifecycle.py`
- Modify: `backend/tests/skills/test_skills_lifecycle.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Add a bootstrap skills state slice**

```python
@dataclass
class SkillsBootstrapState:
    """L7 shared skills runtime state slice."""

    skill_indexer: Any = None
    skill_loader: Any = None
    skill_executor: Any = None
```

```python
skills: SkillsBootstrapState = field(default_factory=SkillsBootstrapState)
```

- [ ] **Step 2: Implement `SkillsModule`**

```python
class SkillsModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_skills",
            dependencies=("runtime_tools", "runtime_llm", "runtime_configuration"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        if not config.features.enable_skills:
            return

        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")
        init_skills_module(llm_adapter)
        self._context.skills.skill_indexer = get_skill_indexer()
        self._context.skills.skill_loader = get_skill_loader()
        self._context.skills.skill_executor = get_skill_executor()
```

- [ ] **Step 3: Remove shared skills init from `tools/lifecycle.py`**

```python
# delete:
from ..skills.service_access import init_skills_module
init_skills_module(llm_adapter)
```

- [ ] **Step 4: Insert `SkillsModule` into bootstrap order**

```python
from ..skills.lifecycle import SkillsModule
```

```python
ToolsModule(context),
SkillsModule(context),
PersonalityModule(context),
```

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/skills/test_skills_lifecycle.py tests/runtime/test_layer_lifecycle_modules.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/skills/lifecycle.py backend/src/magi/bootstrap/context.py backend/src/magi/bootstrap/builder.py backend/src/magi/tools/lifecycle.py backend/tests/skills/test_skills_lifecycle.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: move shared skills lifecycle into skills layer"
```

## Chunk 3: Remove ChatTaskAgent's Private Skills Runtime

### Task 3: Inject shared `skill_executor` into the chat agent

**Files:**
- Modify: `backend/src/magi/agent/lifecycle.py`
- Modify: `backend/src/magi/agent/task_agents/factory.py`
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
- Modify: `backend/tests/agent/test_chat_task_agent_skills_binding.py`
- Modify: `backend/tests/agent/test_chat_task_agent_orchestration.py`

- [ ] **Step 1: Thread shared `skill_executor` through the chat agent factory**

```python
create_chat_agent=create_chat_agent_factory(
    ...,
    skill_executor=self._context.skills.skill_executor,
)
```

```python
def create_chat_agent_factory(..., skill_executor: Any) -> Callable[[str], ChatTaskAgent]:
    ...
```

- [ ] **Step 2: Update `ChatTaskAgent` to accept injected skills runtime**

```python
def __init__(..., skill_executor=None, ...) -> None:
    ...
    self._skill_executor = skill_executor
```

```python
self.function_calling_executor = FunctionCallingExecutor(
    ...,
    skill_executor=self._skill_executor,
)
```

- [ ] **Step 3: Delete private constructor logic**

```python
# delete:
self._skill_indexer = SkillIndexer()
self._skill_loader = SkillLoader(self._skill_indexer)
self._skill_executor = SkillExecutor(self._skill_loader, llm_adapter)
```

- [ ] **Step 4: Run focused agent tests**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/agent/test_chat_task_agent_skills_binding.py tests/agent/test_chat_task_agent_orchestration.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/lifecycle.py backend/src/magi/agent/task_agents/factory.py backend/src/magi/agent/task_agents/chat_task_agent.py backend/tests/agent/test_chat_task_agent_skills_binding.py backend/tests/agent/test_chat_task_agent_orchestration.py
git commit -m "refactor: inject shared skills runtime into chat agent"
```

## Chunk 4: Align Runtime Exports And Regression Coverage

### Task 4: Export shared skills bindings from bootstrap-owned state and verify regressions

**Files:**
- Modify: `backend/src/magi/bootstrap/exports.py`
- Modify: `backend/tests/api/test_skills_router.py`
- Modify: `backend/tests/runtime/test_layer_lifecycle_modules.py`

- [ ] **Step 1: Export skills bindings from context state**

```python
skill_indexer = self._context.skills.skill_indexer
skill_loader = self._context.skills.skill_loader
skill_executor = self._context.skills.skill_executor
```

```python
if skill_indexer is not None:
    container.skill_indexer.override(providers.Object(skill_indexer))
```

- [ ] **Step 2: Keep API skills flow green**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/api/test_skills_router.py -q`
Expected: PASS

- [ ] **Step 3: Run the A5 regression suite**

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/skills/test_skills_lifecycle.py tests/agent/test_chat_task_agent_skills_binding.py tests/runtime/test_layer_lifecycle_modules.py tests/agent/test_chat_task_agent_orchestration.py tests/api/test_skills_router.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/bootstrap/exports.py backend/tests/api/test_skills_router.py backend/tests/runtime/test_layer_lifecycle_modules.py
git commit -m "refactor: finalize shared skills lifecycle ownership"
```

## Notes

- A5 intentionally does **not** redesign `skills/service_access.py` into a new public API. It remains the skills-layer owner of the shared runtime objects; the change here is that lifecycle ownership and agent consumption become single-path.
- A5 intentionally does **not** remove API-level helpers such as `api/services/skills_runtime_service.py`. Those wrappers were introduced by A4 and remain valid as service adapters over the shared skills runtime.
- A5 intentionally does **not** tackle prompt assembly or retrieval shaping. Those concerns stay in A7.

## Verification Handoff

After the last task, run the full A5 regression suite once more:

Run: `cd /Users/asuka/code/magi/backend && PYTHONPATH=src pytest tests/skills/test_skills_lifecycle.py tests/agent/test_chat_task_agent_skills_binding.py tests/runtime/test_layer_lifecycle_modules.py tests/agent/test_chat_task_agent_orchestration.py tests/api/test_skills_router.py -q`
Expected: PASS

Plan complete and saved to `docs/superpowers/plans/2026-03-16-a5-skills-lifecycle-unification.md`. Ready to execute?
