# Product Configuration Guide

## Purpose

This document describes the main product-facing configuration surfaces in Magi.

It is intended for:

- new contributors working on onboarding, settings, or configuration UX
- open source users who want to understand what the product can configure today
- maintainers who need one place to review the expected behavior of language, model, memory, and tool settings

## Configuration Areas

Magi currently exposes these major configuration areas:

- language and localization
- onboarding flow
- LLM provider and model settings
- AI personality and tone
- memory system
- tool management
- plugin management
- sensor source management
- settings page structure

These areas are closely related. Onboarding determines the first-run experience, while the settings page is the long-term place where users revisit the same configuration families.

## Alpha Product Focus

The current Alpha product path is **Chat with Memory + Evidence Trace**.

This means the most important first-run and everyday workflow is:

- complete onboarding quickly enough to reach chat
- configure an LLM provider and a usable default model
- choose or create a persona without needing file-system knowledge
- send messages and receive reliable replies
- ask explicit memory-recall questions
- see enough evidence to understand which memories informed an answer

Core surfaces for this path:

- chat conversation flow
- memory recall and answer evidence
- onboarding quick setup
- settings for LLM, conversation, memory, and persona basics

Surfaces that remain supported but are not the Alpha polish target:

- timeline browsing
- plugin marketplace and plugin package management
- advanced memory/operator panels
- detailed runtime inspection surfaces

Expert and operator surfaces should stay available when they help development or diagnosis, but they should not be pushed into quick onboarding or the ordinary chat path. Deep personality evolution, memory worker process isolation, and all-package backend typing strictness are follow-up work unless profiling or product validation shows they are required for the Alpha path.

## Language And Localization

Magi currently supports:

- Simplified Chinese
- English

Expected behavior:

- users can switch language at any time
- language preference is persisted
- the application re-renders in the chosen language
- onboarding and settings must remain language-aware

Implementation notes:

- new user-facing UI copy should continue to use i18n keys rather than hardcoded text
- `zh-CN` and `en` resources should stay aligned
- language changes should keep local state, persisted preference, and document language in sync

## Onboarding Flow

The onboarding flow is the first-run configuration experience.

Current design expectations:

- if onboarding is incomplete, the application routes the user into onboarding
- if onboarding is already complete, the user enters the main application
- onboarding uses a dedicated layout rather than the main application shell
- partially completed onboarding progress should survive refreshes or temporary exits

The onboarding flow distinguishes two modes:

- quick mode
  Focus on essential setup only

- expert mode
  Expose the full configuration surface

### Quick Mode

Quick mode is intended to reduce friction for first-time users.

It should focus on:

- language
- LLM configuration
- AI personality

### Expert Mode

Expert mode exposes the full configuration path, including:

- language
- LLM configuration
- AI personality
- memory configuration
- tool configuration

## Settings Page

The settings page is the persistent configuration home after onboarding.

It should provide a stable place where users can revisit and update:

- preferences
- LLM settings
- conversation settings
- personality settings
- memory settings
- code agent settings
- timeline settings
- plugin settings
- tool settings
- relevant system/runtime settings

Expected behavior:

- settings are grouped by category
- changes are validated before save
- save success and validation errors are visible to the user
- language switching remains available from settings
- desktop conversation settings can include a default chat workspace directory used when creating new conversations
- persisted editable values should continue to load through the main configuration document instead of ad-hoc menu-specific payloads
- read-only registries, templates, and runtime status payloads should stay on dedicated domain endpoints rather than being embedded into the main configuration document

## Preferences

The preferences area owns user-facing behavior toggles that are not model-specific.

Current product expectations:

- users can switch interface language at any time
- desktop users can choose whether closing the main window hides to tray or exits
- packaged desktop builds should expose a manual update surface that checks the latest published stable GitHub Release, downloads signed updater artifacts, and prompts for restart after installation
- desktop chat surfaces should show the active conversation workspace and allow per-session overrides
- when neither a global default nor a per-session override is set, desktop chat should fall back to a managed local workspace under `~/.magi/chat-workspace`
- desktop chat attachments should be uploaded into managed local runtime storage before a turn is sent
- desktop chat should support image, text-like, and PDF attachments with backend-side normalization metadata
- desktop chat composers should present selected attachments as removable blocks before send and preserve them in message history
- desktop chat composers should separate attachment chips, message input, and toolbar controls so attachment UI does not shift the text caret region
- image attachments preserved in message history should render as thumbnails on desktop chat surfaces
- desktop chat history thumbnails should open a larger local preview when clicked
- parsed text and PDF attachments should be injected into the chat prompt as active attachment context for the current turn
- image attachments on vision-capable core models should be delivered as multimodal message blocks and routed through direct LLM execution
- conversation preferences should allow users to decide whether the assistant may inspect prepared media attachments for grounded replies; media grounding must remain disabled unless the selected core model exposes vision capability
- conversation rhythm may split one assistant turn into several natural chat bubbles when enabled; it takes precedence over streaming output for that turn, must remain presentation-only, preserve one canonical answer for memory and trace, and fall back to a single message when planning is unavailable or invalid

## Conversation Settings

The conversation settings area owns conversation-scoped defaults that are not model-specific.

Current product expectations:

- desktop users can set a default chat workspace directory for new conversations
- the default configuration template should seed the managed local workspace path as `~/.magi/chat-workspace`
- clearing the saved default workspace should fall back to the managed local workspace behavior instead of breaking new conversations
- clearing the default chat workspace should fall back to provider-independent runtime defaults
- per-conversation workspace changes should not overwrite the saved global default
- automatic long-task background routing should default to off; when enabled, Magi may use rule and model classification to move likely long-running chat turns to background execution
- when automatic long-task background routing is off, users should still be able to move an active task to the background manually from the chat surface

## Code Agent Settings

The code agent settings area controls whether Magi may hand larger code changes to installed external coding CLIs.

Expected behavior:

- users can disable external code tooling from settings
- users can choose a preferred tool or let Magi automatically pick an installed tool
- detected executable paths should be visible and editable without exposing internal tool names
- global constraints such as blocked paths, git commit/push guidance, and default timeout should use the same form styling as the rest of settings

## LLM Configuration

The LLM configuration layer defines how Magi talks to language models.

Current product expectations:

- providers are explicit configured instances; a fresh config starts with no providers
- multiple provider instances can share the same provider type when they represent different accounts, gateways, or service scopes
- each provider instance stores provider-level default `api_key` and `base_url` values plus service-specific overrides under `services.chat`, `services.embedding`, `services.image_generation`, and future service blocks
- service-specific API credentials and custom Base URLs are optional overrides; blank service fields inherit the provider-level defaults
- expert-facing configuration can expose more fields than quick mode
- provider/model metadata should come from the backend registry rather than hardcoded frontend lists
- each selected model can expose a capability profile such as vision, reasoning, tool calling, and embedding support
- users can review the active model capability profile during onboarding and later in settings
- users add or edit provider instances from provider templates or a custom-provider template
- custom providers may define manual chat model IDs and a selectable default model
- advanced users can override capability flags, model limits, and provider-specific JSON options for the current model
- provider and model catalogs should be delivered by dedicated LLM catalog endpoints that already merge saved provider instances, manual chat/embedding model IDs, and metadata overrides on the backend
- custom-provider creation fields and defaults should be delivered by a dedicated template endpoint rather than piggybacking on generic config responses
- image generation model catalogs should expose provider-owned capability metadata such as supported sizes, supported quality values, maximum image count, and native generation protocol
- image generation runtime configuration is not inferred from chat settings; it uses `services.image_generation` for timeout and native protocol, and uses service-specific API key/Base URL overrides when present before falling back to the provider-level defaults
- built-in native image generation adapters currently cover OpenAI Images, Gemini Imagen via `models:predict`, DashScope multimodal image generation, MiniMax Image, and Z.ai Images; providers without verified native image generation should not expose image models
- image generation models must come from provider-owned registry metadata or native adapter support; manually marking a chat model as `image_output` must not create an image generation model
- generated image artifacts should be persisted into the active chat workspace and, when a chat session/turn is active, imported as managed chat attachments; provider-hosted image URLs are downloaded best-effort before falling back to the original URL
- image generation tool invocations are permission-classified as high risk because they trigger external generation and write local image artifacts

At a minimum, the product should support:

- adding, editing, enabling, disabling, and deleting provider instances
- provider-template selection
- provider-level API key and Base URL input
- collapsible service sections with service-specific API key and custom endpoint override input plus explicit inheritance hints
- service-local model catalog management in the provider editor, with connection testing available from the chat service section
- provider selection per scenario
- model selection
- manual chat model ID entry for custom providers
- model capability summary
- advanced capability override controls for the currently selected model
- image generation model selection constrained to models declared with native image-generation metadata

The exact provider list may evolve, but the product architecture should keep provider configuration extensible rather than hardcoding one vendor path.
The frontend may preview unsaved provider edits, but backend-owned catalog resolution remains the source of truth for how manual models, service-specific availability, and override metadata are interpreted.

## AI Personality

Magi supports configurable assistant personality behavior.

The durable architecture source of truth for persona runtime behavior is [Persona Runtime Architecture](./persona-runtime-architecture.md). Product configuration should treat persona as a structured behavior model rather than a single prompt-style filter.

There are two main ways to express personality:

- preset personalities
- custom personality prompt input

The product should also support a configurable tone layer, such as:

- casual
- formal

Design expectations:

- presets should be loaded from the backend rather than hardcoded into the frontend
- persona identity should flow through the persona registry APIs instead of filename-based UI state
- chat messages store the active `persona_id` as the persona snapshot for that turn; display names and avatars are resolved from the current persona registry record at render time
- chat response generation should also resolve prompt identity from the stored turn `persona_id`, so switching the active persona after enqueue does not change the persona used for that pending reply
- persona deletion is soft deletion. Ordinary persona lists hide deleted records, while historical chat rendering may use `include_deleted` registry lookups so old messages can still resolve their persona identity.
- personality content should remain language-aware
- persona behavior should be planned per turn by the Personality Layer before prompt rendering; final response prompts should receive only the selected register, quiet-hour clamps, active triggers, relationship modifiers, and dynamic-state modulations for that turn
- ordinary low-performance persona expression should be valid most of the time; personality should usually appear through attention bias, judgment, and conversational stance rather than constant catchphrases
- state-transition behavior should be replaced by signature triggers and quiet-hour clamps; analysis, worker, and tool-result rendering should use task or analysis registers instead of inheriting casual-chat performance
- quick mode should stay simpler than expert mode

The custom personality editor should progressively expose:

- identity, values, attention biases, and baseline voice
- registers for task, casual, analysis, emotional, and crisis turns
- signature triggers that make the persona more visible only under relevant conditions
- quiet hours that intentionally reduce persona intensity
- relationship-depth layers that modify trigger thresholds, memory behavior, and expression bounds rather than replacing the whole tone
- dynamic-state rules that map mood, energy, and stress into concrete behavior changes
- few-shot examples by register, including ordinary baseline examples

## Memory System

Magi now exposes a lifecycle-based memory system instead of the older feature-stacked memory layer framing.

The current conceptual model is:

- `L0`: working context
  Short-lived runtime state kept in memory with checkpoint recovery

- `L1`: event memory
  Long-term normalized source events and the factual base for later recall

- `L2`: structured cognition
  Entities, relationships, and defensive ToM assertions derived from L1

- `L3`: reflection memory
  Summaries and distilled insights generated from retained event streams

- `L4`: procedural memory
  Reusable strategies, execution heuristics, and learned failure avoidance

Product expectations:

- users can understand the lifecycle of memory at a high level
- ordinary users should see memory through natural-language recall, evidence, and correction workflows before seeing layer-specific internals
- advanced memory configuration remains expert-oriented
- L0-L4 workbench and inspector surfaces should be treated as expert/operator tooling, not as the default user memory experience
- quick onboarding should not force detailed memory tuning
- settings should expose the main lifecycle toggles and key pipeline switches
- general memory settings should expose the managed local storage directory used for memory databases
- general memory settings should expose a global hot-memory retention window and whether aged history is deleted or archived
- general memory settings should also expose retrieval reranker controls, including whether LLM reranking is enabled, whether it runs locally or remotely, and where managed local reranker models are stored
- vector writes should always stay on the async sqlite path rather than being user-configurable
- the Knowledge Memory workspace should let operators manually trigger immediate L2 microbatch generation for all currently staged batches

The current settings surface should support at least:

- enable or disable `L0` through `L4`
- configure L0 checkpoint interval
- configure a global memory retention window
- choose whether aged history is deleted or archived into date-partitioned archive databases
- enable or disable memory retrieval reranking
- choose reranker execution mode (`local` or `remote`)
- configure reranker candidate count and timeout budget
- configure local reranker model reference (`managed` cache ID or external file path)
- enable or disable L3 LLM reflection

Important behavioral rules:

- `L1` is the long-term foundation
- `L2`, `L3`, and `L4` depend on `L1`
- runtime telemetry should not be treated as equivalent to user-authored memory
- user-visible chat transcript is not owned by `L1`; it is owned by the dedicated chat domain store
- expert memory controls belong in Settings and expert onboarding, not quick onboarding

Current storage implementation notes:

- `agent.memory.db_path` points at the managed memory data directory shown in Settings.
- `message_queue.db` is reserved for runtime command persistence, not long-term L1 memory.
- `chat.db` is the product-domain source of truth for chat sessions, turn state, and visible transcript rows.
- L1 is stored in `data/memory/l1_events.db`.
- `data/memory/l1_events.db` is now a lossy canonical projection target for `user_text` and `assistant_final` only; it is not the transcript source of truth.
- when history behavior is `archive`, aged-out hot-path events are copied into `data/memory/archive/YYYY-MM-DD.db` before being removed from the active L1 projection.
- L0/L2/L3/L4 are consolidated into `data/memory/memory.db` (multi-table layout).
- Layer vectors are stored per layer (`L1/L3/L4` vector tables) instead of a shared `embeddings.db`.
- The vector backend is fixed to sqlite and vector writes stay async; Settings no longer exposes backend or scheduling switches.
- Managed local reranker assets belong under `~/.magi/cache/models/rerank/<managed_model_id>/`; externally referenced local reranker files stay in place and are referenced by path only.
- Current `local` reranker execution first tries a configured provider instance such as `llm.providers.local.services.chat` that points to a local OpenAI-compatible service.
- If that local provider path is unavailable and a managed/external local reranker model file is configured, retrieval may fall back to direct `llama-cli` execution against that local model file.
- If neither the local provider path nor the local CLI path is available, retrieval falls back to heuristic reranking.
- `llm_usage.db` lives under `~/.magi/runtime/`.
- `runtime_trace.db` is reserved for execution observability and live runtime notifications, not durable chat transcript recovery.
- rebuildable plugin state belongs under `~/.magi/cache/plugins/<plugin_id>/`, not under memory storage.

## Tool And Plugin Management

Tool management covers:

- builtin tools
- provider-backed tools
- external skills
- plugin-contributed tools
- plugin package lifecycle

Expected product behavior:

- users can inspect discovered plugin packages in a dedicated Plugins area
- users can enable, disable, reload, and rescan plugin packages
- plugin-provided settings are rendered from backend field metadata rather than custom plugin frontend code
- tool surfaces should continue to reflect runtime-registered tools rather than hardcoded frontend lists

Tool-specific expectations:

- users can enable or disable supported builtin or plugin-provided tools
- tool-specific configuration is shown only when relevant
- external skills are discoverable from the backend rather than hardcoded
- expert mode exposes more of this surface than quick mode

The exact tool list may change over time, but the product should preserve these principles:

- clear enable/disable state
- explicit provider configuration where required
- separation between builtin tools and externally loaded skills

## Timeline Source Management

Timeline source management is now plugin-backed.

Expected product behavior:

- the Timeline settings surface should render sources from backend-registered timeline sensors
- the frontend should not assume a fixed source list when the backend can provide dynamic sensor contributions
- timeline ingestion stays on by default, while per-source controls live on the source itself
- per-source behavior such as sync mode, retention, and source-specific fields should be persisted through plugin settings

This split is intentional:

- source-specific runtime settings belong to the owning sensor contribution

Timeline sync behavior is now backed by the unified scheduler runtime.

Expected product behavior:

- manual sync should enqueue a one-shot scheduler job for the selected source
- interval sync should register a recurring schedule when the source is enabled
- watch mode may be offered as a source capability, but a source without native watch support may fall back to interval semantics
- sensor source status may expose scheduler-backed state such as last sync, next run, and last error

## Timeline Review Surface

The main timeline page is a semantic-zoom review surface for the user's own activity and state patterns.

Expected product behavior:

- the page should prioritize a window overview, aggregated state summary, scale-specific review lane, and evidence drawer
- the primary timeline experience should support `month`, `week`, `day`, and `hour` scales without compatibility views for the older feed-style layout
- `month` should emphasize reflection windows and self-state patterns derived from L2/L3 memory
- `week` and `day` should emphasize clustered periods instead of raw one-line logs
- `hour` should reveal raw evidence and fine-grained events
- selecting a timeline anchor should open a context drawer backed by a cross-layer context bundle rather than a page-specific event detail contract
- the product may add more source types over time, but the timeline surface should stay source-agnostic at the page-structure level

## Desktop Window Presence

Magi is a desktop-only application and should behave like a native background-capable desktop app instead of a browser tab wrapped in a shell.

Expected product behavior:

- the application may remain running after the main window is closed
- window-close behavior should be user-configurable from Settings
- the default behavior should preserve the local runtime and hide the main window instead of terminating the app
- the app should expose a persistent desktop presence entry point even when the main window is hidden

### Close-To-Tray Or Menu-Bar Preference

The Preferences surface should expose a desktop behavior toggle:

- `Close window to tray/menu bar`

Expected behavior:

- the toggle is enabled by default
- the preference is persisted with the rest of product settings
- when enabled, clicking the main window close control hides the main window and keeps the app resident
- when disabled, clicking the main window close control should follow the normal exit flow

Implementation boundary:

- the frontend owns the user-facing setting, copy, and confirmation dialog experience
- the desktop shell owns interception of native close events, visibility changes, and final process termination

### Platform-Specific Presence Surface

The product behavior should stay conceptually aligned across operating systems while still respecting system conventions.

- macOS
  Use a menu-bar status item as the persistent presence surface. Closing the main window should hide it, not terminate the runtime, when the close-to-tray setting is enabled.

- Windows
  Use a notification-area tray icon as the persistent presence surface. Closing the main window should hide it to the tray when the close-to-tray setting is enabled.

- Linux
  Use a system tray icon where the desktop environment supports it. Closing the main window should hide it to the tray when the close-to-tray setting is enabled.

The persistent presence surface should provide these actions:

- open
- settings
- quit

Expected behavior:

- `open` restores and focuses the main window
- `settings` restores the main window and routes directly into Settings
- `quit` performs a real application exit rather than merely hiding the window

### Exit Confirmation

When the user requests a real exit from the persistent presence surface, the product should warn that local runtime work will stop.

Expected behavior:

- quitting from the tray or menu bar should require confirmation
- the confirmation should explain that backend tasks and the local runtime will be terminated
- canceling the confirmation should keep the app resident
- hiding the window through the native close control should not trigger the quit confirmation when the close-to-tray setting is enabled

### Runtime Ownership Rule

Hiding the window is not equivalent to shutting down the desktop runtime.

Important rule:

- ordinary close-to-tray behavior must not stop the Python backend processes or other desktop runtime services
- backend shutdown should happen only during an explicit quit flow or unrecoverable application termination

## Cross-Cutting Product Rules

These rules apply across onboarding and settings:

- quick mode should optimize for speed and low cognitive load
- expert mode should optimize for clarity and control
- configuration should be language-aware
- configuration changes should be persisted
- validation should happen before save
- advanced features should not be forced on new users too early

## Relationship To Runtime Docs

This document is product-facing.

For internal runtime implementation details, read:

- [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)

For unified plugin loading and plugin-backed sensors, read:

- [Unified Plugin Architecture](./plugin-extension-architecture.md)
- [Plugin Development Guide](./plugin-development-guide.md)

For a high-level repository and architecture introduction, read:

- [Project Overview](./project-overview.md)
