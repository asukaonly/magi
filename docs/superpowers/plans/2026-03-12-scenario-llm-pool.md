# Scenario LLM Pool Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single global LLM config with a scenario-based provider pool and ship the corresponding backend, runtime, onboarding, and settings changes for `context_decider` and `core`.

**Architecture:** Move connection details into `llm.providers`, move model choices into `llm.selections`, and add a global `ScenarioLLMPool` that resolves adapters by scenario. Runtime consumers stop owning their own global adapter assumptions, while the frontend splits `LLM` into scenario model selection and provider configuration using the same structure in onboarding and settings.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, React 18, TypeScript, Vite, Vitest, Testing Library

---

## File Structure

### Backend configuration and API

- Modify: `backend/src/magi/config/models.py`
  Replace the old flat `LLMSettings` shape with provider-pool and scenario-selection models.
- Modify: `backend/src/magi/config/llm_registry.py`
  Resolve capability and limit profiles for scenario selections instead of one global LLM.
- Modify: `backend/src/magi/config/loader.py`
  Load, persist, and default the new `llm.providers` and `llm.selections` structure.
- Modify: `backend/src/magi/api/routers/config.py`
  Expose the new config payload shape, onboarding template, validation, and save behavior.
- Test: `backend/tests/test_config_api.py`
  Validate config serialization, update paths, and registry-driven defaults.
- Test: `backend/tests/test_config_loader.py`
  Validate the loader reads and saves the new LLM shape.

### Backend runtime and adapter resolution

- Create: `backend/src/magi/llm/scenario_pool.py`
  Central service that resolves adapters by scenario and caches them.
- Modify: `backend/src/magi/llm/factory.py`
  Build adapters from explicit provider-entry plus scenario-selection input instead of global config.
- Modify: `backend/src/magi/llm/__init__.py`
  Export the new scenario pool entry points.
- Modify: `backend/src/magi/runtime/bootstrap.py`
  Create one shared scenario pool and wire it into runtime services.
- Modify: `backend/src/magi/tools/context_decider.py`
  Resolve `CONTEXT_DECIDER` adapters from the shared pool.
- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
  Accept a pool-backed resolver or scenario-aware adapter source.
- Modify: `backend/src/magi/agent/task_agents/chat/prompt_service.py`
  Use `CORE` via the shared pool.
- Modify: `backend/src/magi/agent/execution/function_calling.py`
  Use `CORE` via the shared pool.
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
  Stop constructing chat services around one global adapter.
- Modify: `backend/src/magi/agent/task_agents/explore/prompt_service.py`
  Use the pool-backed core scenario for first-version explore planning/aggregation.
- Test: `backend/tests/test_scenario_llm_pool.py`
  New focused tests for scenario resolution, caching, and invalid config handling.
- Test: `backend/tests/test_chat_execution_coordinator.py`
  Keep routing behavior stable while pool-backed context decider wiring changes.
- Test: `backend/tests/test_context_decider_thinking_control.py`
  Preserve context-decider-specific request behavior.

### Frontend types and state shaping

- Modify: `frontend/src/api/modules/config.ts`
  Replace the flat `LLMConfig` type with provider-pool and selection models.
- Modify: `frontend/src/components/config-forms/LLMForm.tsx`
  Reduce orchestration responsibility and delegate to focused sections.
- Create: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
  Render inline-editable scenario cards for `context_decider` and `core`.
- Create: `frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
  Render the provider list and detail panel with built-in model chips.
- Modify: `frontend/src/components/onboarding/OnboardingFlow.tsx`
  Keep onboarding aligned with the new LLM information architecture.
- Modify: `frontend/src/pages/Settings.tsx`
  Keep draft-save behavior working with the new LLM payload shape.
- Test: `frontend/src/__tests__/configForms.test.tsx`
  Cover model-selection and provider-configuration interactions.
- Test: `frontend/src/__tests__/settingsPage.test.tsx`
  Cover draft persistence, validation, and save-blocking behavior.

### Verification

- Modify: `docs/superpowers/specs/2026-03-12-scenario-llm-pool-design.md`
  Only if implementation decisions force a deviation.
- Run backend targeted tests.
- Run frontend targeted tests.
- Perform one manual settings/onboarding verification pass.

## Chunk 1: Backend Config Shape

### Task 1: Replace the flat LLM config models

**Files:**
- Modify: `backend/src/magi/config/models.py`
- Test: `backend/tests/test_config_api.py`

- [ ] **Step 1: Write the failing config-shape test**

```python
def test_system_config_defaults_include_llm_provider_pool_and_selections():
    config = SystemConfigModel()

    assert hasattr(config.llm, "providers")
    assert hasattr(config.llm, "selections")
    assert "context_decider" in config.llm.selections
    assert "core" in config.llm.selections
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_system_config_defaults_include_llm_provider_pool_and_selections -v`
Expected: FAIL because `SystemConfigModel.llm` still exposes the flat shape.

- [ ] **Step 3: Replace `LLMSettings` with provider-pool and selection models**

```python
class LLMScenario(str, Enum):
    CONTEXT_DECIDER = "context_decider"
    CORE = "core"


class LLMProviderEntry(BaseModel):
    enabled: bool = True
    provider_type: str
    display_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    api_format: Optional[str] = None


class LLMSelectionSettings(BaseModel):
    provider_id: str
    model: str
    capability_override_enabled: bool = False
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    providers: Dict[str, LLMProviderEntry] = Field(default_factory=dict)
    selections: Dict[str, LLMSelectionSettings] = Field(default_factory=dict)
```

- [ ] **Step 4: Add validation for required scenarios and built-in uniqueness**

```python
@model_validator(mode="after")
def validate_required_llm_scenarios(self) -> "LLMSettings":
    for scenario_name in ("context_decider", "core"):
        if scenario_name not in self.selections:
            raise ValueError(f"Missing required LLM selection: {scenario_name}")
    return self
```

- [ ] **Step 5: Run test to verify the new shape passes**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_system_config_defaults_include_llm_provider_pool_and_selections -v`
Expected: PASS

- [ ] **Step 6: Add regression tests for uniqueness and required scenarios**

```python
import pytest


def test_llm_settings_reject_duplicate_builtin_provider_types():
    with pytest.raises(ValueError):
        LLMSettings(
            providers={
                "openai": {"provider_type": "openai", "display_name": "OpenAI"},
                "openai_copy": {"provider_type": "openai", "display_name": "OpenAI Copy"},
            },
            selections={
                "context_decider": {"provider_id": "openai", "model": "gpt-5.2"},
                "core": {"provider_id": "openai", "model": "gpt-5.2"},
            },
        )
```

- [ ] **Step 7: Run the focused config tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/config/models.py backend/tests/test_config_api.py
git commit -m "refactor: replace flat llm config shape"
```

### Task 2: Update config loader and config router models

**Files:**
- Modify: `backend/src/magi/config/loader.py`
- Modify: `backend/src/magi/api/routers/config.py`
- Test: `backend/tests/test_config_api.py`
- Test: `backend/tests/test_config_loader.py`

- [ ] **Step 1: Write the failing router test for update paths**

```python
def test_build_update_paths_contains_llm_provider_pool_and_selections():
    config = SystemConfigModel()
    updates = _build_update_paths(config)

    assert "llm.providers" in updates
    assert "llm.selections" in updates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_build_update_paths_contains_llm_provider_pool_and_selections -v`
Expected: FAIL because update paths still target the flat fields.

- [ ] **Step 3: Replace the config router response models**

```python
class LLMProviderConfigModel(BaseModel):
    enabled: bool = True
    provider_type: str
    display_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    api_format: Optional[str] = None


class LLMSelectionConfigModel(BaseModel):
    provider_id: str
    model: str
    capability_override_enabled: bool = False
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Update `_build_llm_config_model`, `_build_update_paths`, and onboarding template generation**

```python
def _build_llm_config_model(...) -> LLMConfigModel:
    return LLMConfigModel(
        providers=...,
        selections=...,
    )
```

- [ ] **Step 5: Update loader defaults to write the new YAML shape**

```python
default_config = {
    "llm": {
        "providers": {
            "openai": {
                "enabled": True,
                "provider_type": "openai",
                "display_name": "OpenAI",
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
            }
        },
        "selections": {
            "context_decider": {"provider_id": "openai", "model": "gpt-5.2"},
            "core": {"provider_id": "openai", "model": "gpt-5.2"},
        },
    },
}
```

- [ ] **Step 6: Add validation tests for disabled-provider references**

```python
def test_config_router_rejects_selection_pointing_to_disabled_provider():
    config = SystemConfigModel()
    config.llm.providers["openai"].enabled = False
    config.llm.selections["core"].provider_id = "openai"

    with pytest.raises(ValueError):
        _build_update_paths(config)
```

- [ ] **Step 7: Run focused backend config tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py tests/test_config_loader.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/config/loader.py backend/src/magi/api/routers/config.py backend/tests/test_config_api.py backend/tests/test_config_loader.py
git commit -m "refactor: expose scenario llm config api"
```

## Chunk 2: Scenario Pool Runtime

### Task 3: Add the shared scenario LLM pool

**Files:**
- Create: `backend/src/magi/llm/scenario_pool.py`
- Modify: `backend/src/magi/llm/factory.py`
- Modify: `backend/src/magi/llm/__init__.py`
- Test: `backend/tests/test_scenario_llm_pool.py`

- [ ] **Step 1: Write the failing pool test**

```python
async def test_scenario_llm_pool_returns_distinct_adapters_for_distinct_scenarios():
    pool = ScenarioLLMPool(config=build_test_config())

    context_llm = pool.get(LLMScenario.CONTEXT_DECIDER)
    core_llm = pool.get(LLMScenario.CORE)

    assert context_llm.model_name == "gpt-5-mini"
    assert core_llm.model_name == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_scenario_llm_pool.py::test_scenario_llm_pool_returns_distinct_adapters_for_distinct_scenarios -v`
Expected: FAIL because `ScenarioLLMPool` does not exist.

- [ ] **Step 3: Implement the pool and scenario enum**

```python
class LLMScenario(str, Enum):
    CONTEXT_DECIDER = "context_decider"
    CORE = "core"


class ScenarioLLMPool:
    def __init__(self, config: AppConfig, adapter_factory=create_llm_adapter):
        self._config = config
        self._adapter_factory = adapter_factory
        self._cache: dict[LLMScenario, LLMAdapter] = {}

    def get(self, scenario: LLMScenario) -> LLMAdapter:
        if scenario not in self._cache:
            self._cache[scenario] = self._build_adapter(scenario)
        return self._cache[scenario]
```

- [ ] **Step 4: Refactor the adapter factory to accept explicit inputs**

```python
def create_llm_adapter(*, provider_type: str, api_key: str, model: str, base_url: str | None) -> LLMAdapter:
    ...
```

- [ ] **Step 5: Add invalid-config tests**

```python
def test_scenario_llm_pool_rejects_disabled_provider_reference():
    pool = ScenarioLLMPool(config=build_disabled_provider_config())

    with pytest.raises(ValueError, match="disabled provider"):
        pool.get(LLMScenario.CORE)
```

- [ ] **Step 6: Add cache invalidation coverage**

```python
def test_scenario_llm_pool_refresh_rebuilds_cached_adapter():
    pool = ScenarioLLMPool(config=build_test_config())
    first = pool.get(LLMScenario.CORE)
    pool.refresh(build_updated_config())
    second = pool.get(LLMScenario.CORE)
    assert second is not first
```

- [ ] **Step 7: Run the scenario pool tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_scenario_llm_pool.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/llm/scenario_pool.py backend/src/magi/llm/factory.py backend/src/magi/llm/__init__.py backend/tests/test_scenario_llm_pool.py
git commit -m "feat: add scenario llm pool"
```

### Task 4: Rewire runtime consumers to use the shared pool

**Files:**
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: `backend/src/magi/tools/context_decider.py`
- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
- Modify: `backend/src/magi/agent/task_agents/chat/prompt_service.py`
- Modify: `backend/src/magi/agent/execution/function_calling.py`
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
- Modify: `backend/src/magi/agent/task_agents/explore/prompt_service.py`
- Test: `backend/tests/test_context_decider_thinking_control.py`
- Test: `backend/tests/test_chat_execution_coordinator.py`
- Test: `backend/tests/test_chat_task_agent_prompt_modules.py`

- [ ] **Step 1: Write the failing runtime wiring test**

```python
async def test_context_decider_uses_context_scenario_from_pool(monkeypatch):
    pool = RecordingScenarioLLMPool()
    decider = ContextDecider(tool_registry=tool_registry, llm_pool=pool)
    await decider.decide("hello")
    assert pool.requested == [LLMScenario.CONTEXT_DECIDER]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_context_decider_thinking_control.py::test_context_decider_uses_context_scenario_from_pool -v`
Expected: FAIL because `ContextDecider` still takes a direct adapter.

- [ ] **Step 3: Change `ContextDecider` to request adapters from the pool**

```python
class ContextDecider:
    def __init__(self, *, tool_registry: ToolRegistry, llm_pool: ScenarioLLMPool, max_tools: int = 5):
        self._llm_pool = llm_pool

    def _llm(self) -> LLMAdapter:
        return self._llm_pool.get(LLMScenario.CONTEXT_DECIDER)
```

- [ ] **Step 4: Change task-agent LLM services to resolve `CORE` from the pool**

```python
class TaskAgentLLMService:
    def __init__(self, *, llm_pool: ScenarioLLMPool, scenario: LLMScenario, logger_name: str) -> None:
        self._llm_pool = llm_pool
        self._scenario = scenario
```

- [ ] **Step 5: Update bootstrap to create one shared pool and pass it through**

```python
llm_pool = ScenarioLLMPool(config)
chat_agent = ChatTaskAgent(agent_id=agent_id, llm_pool=llm_pool, ...)
```

- [ ] **Step 6: Keep explore and chat prompt services on `CORE` for version one**

```python
self._llm_service = TaskAgentLLMService(
    llm_pool=llm_pool,
    scenario=LLMScenario.CORE,
    logger_name="chat",
)
```

- [ ] **Step 7: Run focused runtime tests**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_context_decider_thinking_control.py tests/test_chat_execution_coordinator.py tests/test_chat_task_agent_prompt_modules.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/runtime/bootstrap.py backend/src/magi/tools/context_decider.py backend/src/magi/agent/task_agents/common/llm_service.py backend/src/magi/agent/task_agents/chat/prompt_service.py backend/src/magi/agent/execution/function_calling.py backend/src/magi/agent/task_agents/chat_task_agent.py backend/src/magi/agent/task_agents/explore/prompt_service.py backend/tests/test_context_decider_thinking_control.py backend/tests/test_chat_execution_coordinator.py backend/tests/test_chat_task_agent_prompt_modules.py
git commit -m "refactor: route runtime llms through scenario pool"
```

## Chunk 3: Frontend LLM Surface

### Task 5: Replace frontend config types and break up the LLM form

**Files:**
- Modify: `frontend/src/api/modules/config.ts`
- Modify: `frontend/src/components/config-forms/LLMForm.tsx`
- Create: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
- Create: `frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Test: `frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing config-form test for built-in model chips**

```tsx
it('shows built-in provider model chips in the provider list', async () => {
  render(
    <Form initialValues={{ llm: buildScenarioLlmValue() }}>
      <LLMForm quickMode={false} />
    </Form>
  );

  expect(await screen.findByText('GPT-5.2')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- configForms.test.tsx`
Expected: FAIL because the current LLM form still renders a flat provider picker.

- [ ] **Step 3: Replace flat frontend LLM types**

```ts
export interface LLMProviderConfigEntry {
  enabled: boolean;
  provider_type: string;
  display_name: string;
  api_key?: string;
  base_url?: string;
  api_format?: ApiFormat;
}

export interface LLMSelectionConfig {
  provider_id: string;
  model: string;
  capability_override_enabled: boolean;
  capabilities: LLMCapabilities;
  limits: LLMLimits;
  provider_options: Record<string, any>;
}
```

- [ ] **Step 4: Extract provider configuration UI into its own section component**

```tsx
export function LLMProviderConfigurationSection(props: SectionProps) {
  return <div>{/* provider list + detail panel */}</div>;
}
```

- [ ] **Step 5: Extract scenario card UI into its own section component**

```tsx
export function LLMModelSelectionSection(props: SectionProps) {
  return <div>{/* context_decider + core cards */}</div>;
}
```

- [ ] **Step 6: Keep `LLMForm.tsx` as the orchestrator**

```tsx
return (
  <div className="space-y-6">
    <LLMModelSelectionSection ... />
    <LLMProviderConfigurationSection ... />
  </div>
);
```

- [ ] **Step 7: Add focused tests for model chips and the two-section layout**

```tsx
it('renders model selection before provider configuration', async () => {
  expect(await screen.findByText(/Context Decider/i)).toBeInTheDocument();
  expect(screen.getByText(/Provider Configuration/i)).toBeInTheDocument();
});
```

- [ ] **Step 8: Run config form tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- configForms.test.tsx`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/modules/config.ts frontend/src/components/config-forms/LLMForm.tsx frontend/src/components/config-forms/LLMModelSelectionSection.tsx frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "feat: split llm settings into scenarios and providers"
```

### Task 6: Implement inline scenario editing and save validation

**Files:**
- Modify: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
- Modify: `frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/components/onboarding/OnboardingFlow.tsx`
- Test: `frontend/src/__tests__/configForms.test.tsx`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing scenario-edit test**

```tsx
it('expands the core scenario card inline and updates model options when provider changes', async () => {
  const user = userEvent.setup();
  renderScenarioForm();

  await user.click(await screen.findByRole('button', { name: /change core llm/i }));
  await user.click(screen.getByRole('combobox', { name: /provider/i }));
  await user.click(screen.getByRole('option', { name: /Anthropic/i }));

  expect(screen.getByRole('option', { name: /Claude Sonnet 4.6/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- configForms.test.tsx`
Expected: FAIL because scenario cards are not editable inline yet.

- [ ] **Step 3: Add inline edit mode to each scenario card**

```tsx
const [editingScenario, setEditingScenario] = useState<LLMScenarioId | null>(null);
```

- [ ] **Step 4: Restrict provider choices to enabled providers**

```tsx
const enabledProviderOptions = Object.entries(value.providers)
  .filter(([, provider]) => provider.enabled)
  .map(([providerId, provider]) => ({ label: provider.display_name, value: providerId }));
```

- [ ] **Step 5: Show a non-blocking vision warning on `core`**

```tsx
const showVisionWarning =
  scenarioId === 'core' &&
  selection.capabilities.vision === false;
```

- [ ] **Step 6: Block save when disabling a referenced provider**

```tsx
const referencedBy = findReferencingScenarios(providerId, value.selections);
if (!nextEnabled && referencedBy.length > 0) {
  setProviderError(providerId, referencedBy);
}
```

- [ ] **Step 7: Mirror the same structure in onboarding quick mode**

```tsx
if (quickMode) {
  return (
    <>
      <LLMProviderConfigurationSection compact />
      <LLMModelSelectionSection compact />
    </>
  );
}
```

- [ ] **Step 8: Add settings-page draft-save tests**

```tsx
it('blocks save when disabling a provider referenced by core llm', async () => {
  ...
});
```

- [ ] **Step 9: Run the focused frontend tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- configForms.test.tsx settingsPage.test.tsx`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/config-forms/LLMModelSelectionSection.tsx frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/pages/Settings.tsx frontend/src/components/onboarding/OnboardingFlow.tsx frontend/src/__tests__/configForms.test.tsx frontend/src/__tests__/settingsPage.test.tsx
git commit -m "feat: add inline scenario llm editing"
```

## Chunk 4: End-to-End Validation

### Task 7: Verify backend and frontend together

**Files:**
- Test: `backend/tests/test_config_api.py`
- Test: `backend/tests/test_config_loader.py`
- Test: `backend/tests/test_scenario_llm_pool.py`
- Test: `backend/tests/test_context_decider_thinking_control.py`
- Test: `backend/tests/test_chat_execution_coordinator.py`
- Test: `backend/tests/test_chat_task_agent_prompt_modules.py`
- Test: `frontend/src/__tests__/configForms.test.tsx`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Run the full targeted backend suite**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py tests/test_config_loader.py tests/test_scenario_llm_pool.py tests/test_context_decider_thinking_control.py tests/test_chat_execution_coordinator.py tests/test_chat_task_agent_prompt_modules.py -v`
Expected: PASS

- [ ] **Step 2: Run the full targeted frontend suite**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- configForms.test.tsx settingsPage.test.tsx`
Expected: PASS

- [ ] **Step 3: Run frontend type-check**

Run: `cd /Users/asuka/code/magi/frontend && npm run type-check`
Expected: PASS

- [ ] **Step 4: Perform manual verification**

```text
1. Open onboarding quick mode and confirm provider configuration appears before model selection.
2. Enable OpenAI and Anthropic with placeholder credentials.
3. Set Context Decider to OpenAI and Core LLM to Anthropic.
4. Change Core LLM to a non-vision model and confirm a warning appears without blocking save.
5. Disable the provider used by Core LLM and confirm save is blocked until the scenario is repointed.
6. Open settings and confirm the same structure and draft-save behavior remain intact.
```

- [ ] **Step 5: Update the spec only if implementation deviated**

```md
## Deviation Note
- Why the implementation diverged
- Scope and impact
- Follow-up plan
```

- [ ] **Step 6: Commit final verification or doc follow-up if needed**

```bash
git add docs/superpowers/specs/2026-03-12-scenario-llm-pool-design.md
git commit -m "docs: note scenario llm implementation follow-up"
```

Only do this commit if the implementation changed the approved design.
