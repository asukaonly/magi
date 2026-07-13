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
- first-run setup
- settings for LLM, conversation, memory, and persona basics

Surfaces that remain supported but are not the Alpha polish target:

- timeline browsing
- plugin marketplace and plugin package management
- advanced memory/operator panels
- detailed runtime inspection surfaces

Expert and operator surfaces should stay available when they help development or diagnosis, but they should not be pushed into first-run onboarding or the ordinary chat path. Deep personality evolution, memory worker process isolation, and all-package backend typing strictness are follow-up work unless profiling or product validation shows they are required for the Alpha path.

## Language And Localization

Magi currently supports:

- Simplified Chinese
- English

Expected behavior:

- first launch uses the browser/system language when no language preference has been saved
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

Safety and configuration ownership rules:

- onboarding eligibility must come from a successfully loaded persisted status; a read failure is a recoverable error and must never be interpreted as incomplete onboarding
- completed installations must not render onboarding through direct navigation, refresh, or stale browser history, and onboarding-specific writes must be rejected after completion
- a failed or invalid onboarding template response must stop the flow and offer retry; the client must not substitute a fresh default configuration
- recovered progress cannot resume beyond model setup without a connection result from the current app session; saved persona and first-context choices may be retained, but the flow must return to model setup for verification
- onboarding writes own only the selected language, LLM configuration, and completion flags; agent, memory, network, personality, tool, timeline, and unrelated preference settings must remain unchanged
- onboarding completion is server-owned state; ordinary settings saves must preserve it and cannot move a completed installation back into onboarding

The current first-run path is intentionally single-lane and progressive. It should
reduce friction for first-time users while leaving the full configuration surface
available in Settings after onboarding.

It focuses on:

- language selection through the welcome screen
- a first-run LLM setup surface that asks for one provider, an API key when the provider requires one, and only the minimal endpoint/model fields needed for OpenAI-compatible relays; local or private OpenAI-compatible custom endpoints may be configured without authentication
- model setup must verify the selected chat model before advancing; a successful manual verification is reused while the provider, API key, endpoint, billing plan, API format, and primary model remain unchanged, and any change to those connection settings requires verification again
- AI persona selection or lightweight persona creation
- the selected persona must be present in the registry and successfully activated before onboarding can leave the persona step; a failure keeps the user on that step with a retry path instead of silently selecting a default
- onboarding-generated personas must keep one stable identity across timeouts and retries so repeated or late create requests resolve to the same persona instead of adding duplicates
- a dedicated first-context step that offers optional user-approved data source cards so Magi can build its first useful context before the first chat
- a final completion handoff whose only job is to enter the main app

Onboarding should not reuse the full Settings LLM editor as the default path. Expert fields such as service-specific endpoints, image generation services, per-scenario model routing, model metadata overrides, and detailed memory/tool settings should remain collapsed or move to Settings after onboarding.

Plugin and sensor activation should stay progressive. The first-run flow may explain that data sources improve context and surface direct connection cards in a dedicated first-context step, but it should not require plugin choices before the user enters the main app. Before showing the first-context step, onboarding should persist the selected LLM configuration and allow the backend runtime to start so source sync jobs are actually consumed instead of only queued. These first-context cards should prioritize historical sources that can immediately backfill useful context; purely forward-looking incremental sources, such as continuous screen capture, belong in later suggestions or Settings. History-heavy sources should use a lightweight first-context sample by default and leave full backfill controls to Settings or later background work. Installable source suggestions should start loading before the first-context step so the page can show connection cards immediately. The first-context view must only render sources confirmed available on the current device and must never manufacture fallback cards. It should show one primary recommendation plus at most two alternatives from different categories, prefer an already-installed source among equivalent siblings, and explain the data scope, locality, and estimated setup time. While availability is loading the UI should show progress; on failure it should offer retry or skip, and a successful empty result should say honestly that no suitable source is available. A selected source finishing its connect flow should keep the user on the first-context step so they can add more sources; skipping the step or explicitly finishing it should mark the first-context prompt complete so the main app does not ask the same question again.

The pre-context persistence described above must use the scoped onboarding save rather than replace the full configuration document.

After the user enters the main application for the first time, the post-onboarding first-context dialog is only a fallback for older installs, interrupted onboarding, or other states where `product_tour_completed` is still false. It should offer optional data-source connection cards, make skipping clear, and hand off to the shared plugin install/connect panel when the user chooses a source. Skipping the prompt or completing the connect flow should mark the prompt complete so the initial persona bootstrap can continue. It should not repeat vector-model setup; missing vector-model guidance belongs in first-run model setup and the first-context step as a non-blocking warning.

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
- desktop system notifications for new messages should default to enabled, with notification previews also enabled by default
- packaged desktop builds should expose a manual update surface that checks the latest published stable GitHub Release, downloads signed updater artifacts, and prompts for restart after installation
- packaged desktop builds should also run a delayed background update check shortly after startup and reuse the global network proxy settings when that proxy is enabled
- global network proxy settings should support optional username and password credentials for authenticated HTTP and SOCKS5 proxies
- built-in outbound request tools, including web search, web fetch, weather, and shell subprocess networking, should use the global network proxy only when it is enabled; disabled proxy settings must not imply the default `127.0.0.1:7890` endpoint
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
- conversation preferences should default to allowing the assistant to inspect prepared image attachments for grounded replies when needed; media grounding must remain disabled unless the selected core model exposes vision capability
- conversation rhythm may split one assistant turn into several natural chat bubbles when enabled; it takes precedence over streaming output for that turn, must remain presentation-only, preserve one canonical answer for memory and trace, and fall back to a single message when segmentation is unavailable or invalid

### Desktop Startup Diagnostics

When the desktop backend cannot finish startup, the frontend should show a diagnosis-oriented failure screen instead of only a generic retry prompt. The screen should include the concrete startup error, the backend log path, and a bounded tail of the latest backend log output.

Current log sources:

- packaged desktop builds: `~/.magi/logs/backend.log`
- desktop dev hot mode: `~/.magi/logs/backend-dev-hot.log`, or `MAGI_BACKEND_LOG_FILE` when that environment variable is set

The log excerpt is for local troubleshooting only. It should stay bounded and should not replace the retry action.

## Conversation Settings

The conversation settings area owns conversation-scoped defaults that are not model-specific.

Current product expectations:

- desktop users can set a default chat workspace directory for new conversations
- the default configuration template should seed the managed local workspace path as `~/.magi/chat-workspace`
- clearing the saved default workspace should fall back to the managed local workspace behavior instead of breaking new conversations
- clearing the default chat workspace should fall back to provider-independent runtime defaults
- per-conversation workspace changes should not overwrite the saved global default
- assistant interjection should default to off until the user enables it
- automatic long-task background routing should default to off; when enabled, Magi may use rule and model classification to move likely long-running chat turns to background execution
- when automatic long-task background routing is off, users should still be able to move an active task to the background manually from the chat surface

## Code Agent Settings

The code agent settings area controls whether Magi may hand larger code changes to installed external coding CLIs.

Expected behavior:

- users can disable external code tooling from settings
- users can choose a preferred tool or let Magi automatically pick an installed tool
- the default preferred tool should be automatic selection
- detected executable paths should be visible and editable without exposing internal tool names
- global constraints such as blocked paths, git commit/push guidance, and default timeout should use the same form styling as the rest of settings

## LLM Configuration

The LLM configuration layer defines how Magi talks to language models.

Current product expectations:

- providers are explicit configured instances; a fresh config starts with no providers
- multiple provider instances can share the same provider type when they represent different accounts, gateways, or service scopes
- each provider instance stores provider-level default `api_key` and `base_url` values plus service-specific overrides under `services.chat`, `services.embedding`, `services.image_generation`, and future service blocks
- provider instances may select a backend-registry `provider_plan` when the same provider offers alternate commercial/runtime plans; a plan can override the default Base URL, default models, service model availability, provider fields, and registry pricing without becoming a separate provider type
- built-in `provider_plan` metadata currently covers Z.ai GLM CodePlan, Alibaba Cloud Model Studio Coding Plan, MiniMax Token Plan, and Xiaomi MiMo Token Plan; each plan may expose selectable country/region endpoints such as China, Global, Singapore, and Europe, and changing the endpoint should update the provider-level Base URL while still allowing advanced manual Base URL overrides
- provider plans must declare their allowed runtime scenarios; the built-in coding/token plans are restricted to interactive chat, context decisions, and direct context compaction, and must not be used for background memory summaries, Timeline narratives, embeddings, or image generation
- background model work requires a normal API-backed provider instance; Settings and onboarding should prevent plan-only providers from being assigned to those scenarios and explain the boundary before save
- provider image generation services should remain disabled by default until the user enables them
- service-specific API credentials and custom Base URLs are optional overrides; blank service fields inherit the provider-level defaults
- Settings can expose more fields than first-run LLM setup
- provider/model metadata should come from the backend registry rather than hardcoded frontend lists
- each selected model can expose a capability profile such as vision, reasoning, tool calling, and embedding support
- model metadata can include provider-published cost values; chat models use input/output token pricing, embedding models use input token pricing, and image generation models use per-image pricing when the provider bills successful generations by count
- fixed-fee coding plans should not inherit pay-as-you-go token rates unless the provider publishes plan-specific token pricing; usage accounting may retain the plan source metadata while leaving calculated cost empty
- provider account quotas and rate limits must not be represented as fixed model metadata because they vary by account, tier, region, and live provider policy
- the configurable concurrency value is a local Magi safety limit, defaults to `4`, and is isolated by provider instance, plan, endpoint host, model, and request family so separate accounts or billing modes do not block each other
- usage accounting should prefer explicit provider-reported cost when present, then fall back to registry chat model pricing for USD-denominated token usage
- prompt-cache diagnostics should be lightweight and privacy-safe: they may record provider cache token counters, stable hashes, sizes, selected strategy, and bounded tool names for troubleshooting, but must not persist raw prompts, tool schemas, message bodies, or tool outputs
- users can review the active model capability profile during onboarding and later in settings
- first-run LLM setup should show whether the selected provider or provider plan includes a vector model; plan-level gaps should explain that the plan is for chat only, background memory and Timeline work need a normal API provider, and memory recall remains keyword-only until an embedding model is configured
- the post-onboarding first-context prompt should surface a one-time vector-model setup reminder before recommending data-source plugins when embeddings are missing
- users add or edit provider instances from provider templates or a custom-provider template
- custom providers may define manual chat model IDs and a selectable default model
- advanced users can override capability flags, context/output limits, model cost metadata, and provider-specific JSON options for the current model; local concurrency belongs to scenario runtime settings instead of model metadata
- provider and model catalogs should be delivered by dedicated LLM catalog endpoints that already merge saved provider instances, manual chat/embedding model IDs, and metadata overrides on the backend
- provider catalog entries should expose available provider plans and resolve selected plan metadata before returning default models, default Base URL, service model lists, and pricing-bearing model metadata to the frontend
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
- provider-plan selection for provider templates that expose alternate plans
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
- first-run persona setup should stay simpler than the full editor

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
- first-run onboarding should not force detailed memory tuning
- settings should expose the main lifecycle toggles and key pipeline switches
- general memory settings should expose a global hot-memory retention window, whether aged history is deleted or archived, and the archive directory when archiving is selected
- the managed memory storage directory remains an internal runtime path until live path switching and migration are supported safely
- general memory settings should also expose retrieval reranker controls, including whether LLM reranking is enabled, whether it runs locally or remotely, and where managed local reranker models are stored
- vector writes should always stay on the async sqlite path rather than being user-configurable
- changing the active embedding model must run a save preflight: model or dimension changes for existing vectors require a strong confirmation and should prompt users to rebuild vectors; remote provider/base URL changes with the same model and dimension may show a softer provenance warning
- general memory settings should expose vector ready counts and a rebuild action backed by a persisted background job, so users can safely recover semantic search after embedding changes
- the Knowledge Memory workspace should let operators manually trigger immediate L2 microbatch generation for all currently staged batches
- L1 event memory should default to a 30-day hot retention window
- graph-spreading recall should default to enabled for relation-assisted memory retrieval

The current settings surface should support at least:

- enable or disable `L0` through `L4`
- configure L0 checkpoint interval
- configure a global memory retention window
- choose whether aged history is deleted or archived into date-partitioned archive databases, with a configurable archive directory
- enable or disable memory retrieval reranking
- choose reranker execution mode (`local` or `remote`)
- configure reranker candidate count and timeout budget
- configure local reranker model reference (`managed` cache ID or external file path)
- enable or disable query expansion and configure the maximum number of expansion queries
- enable or disable graph-spreading recall for relation-assisted memory retrieval
- enable or disable user confirmation reminders for profile-memory conflicts
- configure how long L2 waits before refreshing the About You portrait after assertion changes, so repeated updates can be merged
- enable or disable L3 LLM reflection

Important behavioral rules:

- `L1` is the long-term foundation
- `L2`, `L3`, and `L4` depend on `L1`
- runtime telemetry should not be treated as equivalent to user-authored memory
- user-visible chat transcript is not owned by `L1`; it is owned by the dedicated chat domain store
- expert memory controls belong in Settings and operator tooling, not first-run onboarding
- personal profile settings are user-confirmed facts; memory-derived values may be shown as suggestions, but accepting and saving them is the action that turns them into authoritative profile settings

Current storage implementation notes:

- `agent.memory.db_path` is persisted for forward compatibility, but the current Settings UI hides it until runtime directory switching and migration are implemented; active memory still uses `data/memory/`.
- `message_queue.db` is reserved for runtime command persistence, not long-term L1 memory.
- `chat.db` is the product-domain source of truth for chat sessions, turn state, and visible transcript rows.
- `~/.magi/config/lifecycle.yaml` owns local data lifecycle policy for runtime telemetry, LLM usage rollups, LLM prompt-cache diagnostics, command queue history, scheduler history, sensor fingerprints, chat asset GC, and ephemeral job TTLs; it is copied from `backend/configs/lifecycle.example.yaml` on first run.
- L1 is stored in `data/memory/l1_events.db`.
- `data/memory/l1_events.db` is now a lossy canonical projection target for `user_text` and `assistant_final` only; it is not the transcript source of truth.
- when history behavior is `archive`, aged-out hot-path events are copied into the configured archive directory as `YYYY-MM-DD.db` before being removed from the active L1 projection; the default archive directory is `data/memory/archive/`.
- the global hot-memory retention window currently applies to active L1 history projections and L3 history summaries; it does not prune L2 knowledge or L4 skills.
- L0/L2/L3/L4 are consolidated into `data/memory/memory.db` (multi-table layout).
- Layer vectors are stored per layer (`L1/L2 entity/L2 relation/L3/L4` vector tables) instead of a shared `embeddings.db`.
- The vector backend is fixed to sqlite and vector writes stay async; Settings no longer exposes backend or scheduling switches.
- Vector table identity is strict for incompatible embeddings. Remote vectors are keyed by model, dimension, and text-builder version; local vectors are keyed by model file hash, dimension, and text-builder version. Provider provenance changes are surfaced as warnings but do not invalidate the hard identity by themselves.
- L2 batch flush timing and conflict arbitration thresholds remain internal pipeline strategy defaults rather than ordinary user-facing settings.
- `agent.memory.l2.portrait_projection_refresh_delay_seconds` controls the debounced About You portrait refresh after L2 assertion changes. The default is 120 seconds, and repeated changes for the same user during that window are merged into one refresh.
- `agent.memory.l2.experience_seed_llm_selection_max_per_run` bounds automatic experience-seed LLM selection during each consolidation run; seeds beyond the cap use local selection so background maintenance remains bounded.
- Profile-memory conflict notifications should be routed through the Pending memory page so users can either accept the newer inferred memory or keep the existing user-authoritative memory.
- Managed local reranker assets belong under `~/.magi/cache/models/rerank/<managed_model_id>/`; externally referenced local reranker files stay in place and are referenced by path only.
- Current `local` reranker execution first tries a configured provider instance such as `llm.providers.local.services.chat` that points to a local OpenAI-compatible service.
- If that local provider path is unavailable and a managed/external local reranker model file is configured, retrieval may fall back to direct `llama-cli` execution against that local model file.
- If neither the local provider path nor the local CLI path is available, retrieval falls back to heuristic reranking.
- `llm_usage.db` lives under `~/.magi/runtime/`.
- `llm_usage.db` may include bounded prompt-cache diagnostic rows controlled by `lifecycle.llm_usage.cache_observability`; disabling that setting removes those rows during lifecycle cleanup.
- `runtime_trace.db` is reserved for execution observability and live runtime notifications, not durable chat transcript recovery; raw trace data defaults to a 7-day retention window.
- managed chat attachment and derived text files live under `~/.magi/data/resources/chat/` and are removed when their chat session/history is cleared; periodic orphan sweeps remove old session asset directories that no longer have active chat rows.
- runtime logs are governed by size-based `RotatingFileHandler` limits, not lifecycle row retention.
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
- built-in tool enable switches are enforced at execution time, not just displayed in settings
- weather defaults to keyless Open-Meteo for global first-run usability; QWeather remains available for users who prefer it and requires an API key, with API host kept as an optional override when the default endpoint is not accepted by the account
- web search starts with the configured default provider and may fall back to other configured providers in a deterministic order; tool results should expose the actual provider and whether fallback was used, and repeat identical successful queries may be served from a short-lived in-memory cache
- DuckDuckGo is the keyless default for web search, but its availability depends on user network conditions and anti-bot checks; Brave, Tavily, and Perplexity require user-provided API keys; SearXNG is available when the user provides a trusted self-hosted instance URL
- DuckDuckGo anti-bot challenge responses are terminal for the current turn; the assistant should ask the user to configure another supported search provider instead of retrying the same provider loop
- web fetch should stay simple in ordinary settings: the default tool mode automatically tries direct HTTP first and falls back to browser rendering or curl when needed
- web fetch is primarily for public web content and may reuse successful fetch results from a short-lived in-memory cache; localhost, private-network, link-local, multicast, reserved, and otherwise non-globally-routable targets are blocked before provider execution unless the user explicitly enables private-network fetch and allowlists trusted hostnames, host:port values, IPs, or CIDR ranges
- file read should stay low-friction inside the active conversation workspace; reads outside that workspace are allowed only through the existing permission flow, with sensitive user paths such as SSH, cloud, CLI credential, and netrc files classified as higher risk
- external skills are discoverable from the backend rather than hardcoded
- Settings and operator tooling expose more of this surface than first-run onboarding

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

- first-run onboarding should optimize for speed and low cognitive load
- settings and operator surfaces should optimize for clarity and control
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
