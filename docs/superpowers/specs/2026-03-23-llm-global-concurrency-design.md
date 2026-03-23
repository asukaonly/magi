# LLM Global Concurrency Design

## Summary

This design introduces a process-wide concurrency limiter for LLM requests so that all calls sharing the same provider-model pair respect one global cap.

The limiter covers both chat-style requests and embedding requests. It is configured through provider registry defaults and user-facing overrides from the model selection UI.

## Motivation

The current system has two related problems:

- `L1` embedding work is buffered behind an unbounded queue in [`backend/src/magi/memory/l1/event_store.py`](/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py)
- runtime LLM traffic is not centrally constrained per provider-model pair, so `core`, `L2`, `L3`, and embedding traffic can independently pile into the same upstream quota

Adding backpressure only at the L1 queue is not enough. The real shared bottleneck is the upstream provider quota for a concrete provider-model instance.

## Goals

- Enforce one global concurrency cap for every active provider-model request family
- Include embedding requests in the same design
- Let defaults vary by model and provider from the packaged LLM provider registry
- Let users override the cap from the model selection page via advanced settings
- Preserve scenario-based model selection while making concurrency semantics shared across scenarios
- Add queue backpressure for L1 embedding work so slowed embedding throughput does not become unbounded memory growth

## Non-Goals

- No adaptive rate controller in v1
- No token-per-minute or request-per-minute budgeting in v1
- No provider-specific auto-discovery of safe concurrency values
- No priority scheduling or preemption between scenarios in v1

## Constraints From Current Architecture

- Scenario-based selection is owned by [`backend/src/magi/config/models.py`](/Users/asuka/code/magi/backend/src/magi/config/models.py)
- Packaged provider and model metadata is owned by [`backend/src/magi/config/llm_registry.py`](/Users/asuka/code/magi/backend/src/magi/config/llm_registry.py) and [`backend/configs/llm_providers.yaml`](/Users/asuka/code/magi/backend/configs/llm_providers.yaml)
- Plain chat requests flow through [`backend/src/magi/llm/provider_bridge.py`](/Users/asuka/code/magi/backend/src/magi/llm/provider_bridge.py)
- Embedding requests bypass the provider bridge today and flow through [`backend/src/magi/memory/embedding_service.py`](/Users/asuka/code/magi/backend/src/magi/memory/embedding_service.py)
- Model selection UI is owned by [`frontend/src/components/config-forms/LLMModelSelectionSection.tsx`](/Users/asuka/code/magi/frontend/src/components/config-forms/LLMModelSelectionSection.tsx)

This means the limiter cannot live only inside memory. It must live at the shared LLM runtime layer, with embedding service integration.

## Approaches Considered

### Approach A: Bound Only The L1 Embedding Queue

This would reduce memory blow-up in `L1`, but it would not coordinate `core`, `L2`, `L3`, and embedding traffic against the same upstream quota.

Rejected because it only moves the bottleneck.

### Approach B: Global Provider-Model Semaphore

This approach creates a process-wide semaphore for each concrete provider-model request family and makes both chat and embedding calls acquire permits before touching the adapter.

Accepted for v1 because it matches the desired product semantics while staying implementable inside the current architecture.

### Approach C: Full Dynamic Rate Controller

This would add provider-aware RPM or TPM budgets with live adaptation on `429` responses.

Deferred because it is significantly more complex and not required to solve the immediate backlog and burst problem.

## Recommended Design

## 1. Shared Concurrency Semantics

Concurrency is shared by request family, not by scenario.

The user-visible rule is:

- if multiple scenarios use the same chat model, they share one concurrency cap
- embedding models have their own shared cap

Internally the limiter key should be based on:

- resolved runtime provider type
- normalized provider endpoint identity
- model name
- request family: `chat` or `embedding`

The provider endpoint identity should include the normalized `base_url` host so different custom gateways do not accidentally share a bucket.

## 2. Configuration Model

The design uses two layers of configuration:

- packaged defaults from the provider registry
- user overrides from main config

### 2.1 Registry Defaults

Extend model metadata so each packaged model can declare a default concurrency limit.

For chat models, add `max_concurrency` alongside existing model limits.

For embedding models, add a comparable limit field so embedding defaults also come from the registry.

Registry ownership remains in:

- [`backend/configs/llm_providers.yaml`](/Users/asuka/code/magi/backend/configs/llm_providers.yaml)
- [`backend/src/magi/config/llm_registry.py`](/Users/asuka/code/magi/backend/src/magi/config/llm_registry.py)

### 2.2 User Overrides

Do not store the override directly on each scenario selection. That would create conflicts when `core`, `L2`, and `L3` point at the same model but set different values.

Instead add a shared override map to `LLMSettings`, keyed by a canonical model runtime key.

Recommended shape:

- `llm.model_runtime_overrides`
- key: `provider_id::model::request_family`
- value: `max_concurrency`

This preserves one source of truth for each shared limiter bucket.

## 3. Runtime Components

### 3.1 New Limiter Service

Add a new runtime-owned service under `backend/src/magi/llm/`, for example:

- `concurrency_limiter.py`

Responsibilities:

- own a process-wide semaphore per normalized limiter key
- create semaphores lazily from effective config
- expose a helper like `run_with_limit(key, coroutine_factory)`
- expose lightweight runtime statistics such as active count, waiting count, and configured limit

### 3.2 Chat Request Integration

Wrap outbound provider calls in [`backend/src/magi/llm/provider_bridge.py`](/Users/asuka/code/magi/backend/src/magi/llm/provider_bridge.py).

Coverage:

- `chat_response()`
- `chat_with_tools()`

The limiter should sit outside provider-specific branching so it consistently covers all providers.

### 3.3 Embedding Request Integration

Wrap outbound embedding calls in [`backend/src/magi/memory/embedding_service.py`](/Users/asuka/code/magi/backend/src/magi/memory/embedding_service.py).

Coverage:

- `embed_text()`
- `embed_texts()`

This is required because embedding requests currently bypass `LLMProviderBridge`.

## 4. Effective Limit Resolution

Effective concurrency should resolve in this order:

1. user override from `llm.model_runtime_overrides`
2. packaged model default from provider registry
3. request-family fallback

Recommended fallback policy:

- chat fallback: conservative shared default
- embedding fallback: moderate default
- custom providers: low fallback unless the user overrides

The exact numbers can stay in packaged config rather than hardcoded in logic.

## 5. L1 Embedding Queue Backpressure

Global concurrency limiting slows embedding throughput intentionally. Because of that, the current unbounded queue in [`backend/src/magi/memory/l1/event_store.py`](/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py) also needs a bounded backlog.

v1 design:

- change the queue to a bounded queue
- keep enqueue semantics lossless
- if the queue is full, await capacity instead of dropping work
- add runtime stats for queue size and saturation

This gives controlled backpressure instead of unbounded memory growth.

## 6. Frontend UX

Model selection remains scenario-based, but advanced concurrency editing writes to the shared override entry for the selected provider-model-family key.

The UI entry point stays in:

- [`frontend/src/components/config-forms/LLMModelSelectionSection.tsx`](/Users/asuka/code/magi/frontend/src/components/config-forms/LLMModelSelectionSection.tsx)

UX rules:

- add an `Advanced` section on each scenario card
- expose `Max Concurrency`
- if the selected model is shared by other scenarios, show a hint that the value is shared
- expose the same control for the embedding scenario
- keep the control in expert surfaces; do not force it into quick mode

The front-end config types remain centered in:

- [`frontend/src/api/modules/config.ts`](/Users/asuka/code/magi/frontend/src/api/modules/config.ts)

## 7. Observability

Add at least these backend stats:

- current active requests per limiter key
- current waiting requests per limiter key
- configured limit per limiter key
- L1 embedding queue size
- L1 embedding queue saturation count or wait count

This is important because concurrency bugs look like latency spikes and queue growth rather than direct exceptions.

## 8. Error Handling

The limiter is concurrency control, not retry logic.

Expected behavior:

- request waits for a permit before upstream call
- provider `429` handling continues to live in the request path
- limiter does not permanently shrink or expand itself in v1
- cancellation must release permits correctly

## 9. Testing Strategy

Required coverage:

- config resolution for registry default versus shared override
- limiter key normalization for built-in and custom providers
- provider bridge requests sharing permits across scenarios that point to the same chat model
- embedding service requests sharing permits for the same embedding model
- bounded L1 queue backpressure behavior
- frontend advanced control reading and writing the shared override entry

## 10. Rollout Order

Recommended implementation order:

1. backend config and registry schema
2. limiter service
3. provider bridge integration
4. embedding service integration
5. bounded L1 embedding queue
6. frontend advanced model control
7. observability and tests

## Open Decisions

The main design choice already resolved for this spec is that concurrency is global per provider-model-family, not per scenario.

Remaining implementation-time details that can stay internal:

- exact fallback defaults for models without packaged values
- exact queue bound for L1 embedding staging
- exact telemetry API shape for limiter stats
