// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgentConfigModel */
        AgentConfigModel: {
            /**
             * Description
             * @default Magi AI Agent Framework
             */
            description: string | null;
            /**
             * Name
             * @default magi-agent
             */
            name: string;
        };
        /** BootstrapConfigModel */
        BootstrapConfigModel: {
            /**
             * Max Rounds
             * @default 3
             */
            max_rounds: number;
            /** Opening Examples */
            opening_examples: string[];
            /**
             * Opening Line
             * @default
             */
            opening_line: string;
            /**
             * Style Instruction
             * @default
             */
            style_instruction: string;
        };
        /** ClaudeCodeSettings */
        ClaudeCodeSettings: {
            /**
             * Allowed Tools
             * @default Read Edit Write Grep Glob Bash(git diff*) Bash(git status*) Bash(pytest*)
             */
            allowed_tools: string;
            /**
             * Binary Path
             * @default
             */
            binary_path: string;
            /**
             * Default Model
             * @default
             */
            default_model: string;
            /**
             * Disallowed Tools
             * @default Bash(git push*) Bash(git commit*) Bash(rm*)
             */
            disallowed_tools: string;
            /** Extra Args */
            extra_args: string[];
            /**
             * Max Budget Usd
             * @default 5
             */
            max_budget_usd: number;
        };
        /** CodeAgentProbeResponse */
        CodeAgentProbeResponse: {
            results: components["schemas"]["CodeAgentProbeResults"];
        };
        /** CodeAgentProbeResults */
        CodeAgentProbeResults: {
            claude_code: components["schemas"]["ProbeResult"];
            codex: components["schemas"]["ProbeResult"];
        };
        /** CodeAgentSettings */
        CodeAgentSettings: {
            /**
             * Auto Apply
             * @default false
             */
            auto_apply: boolean;
            claude_code: components["schemas"]["ClaudeCodeSettings"];
            codex: components["schemas"]["CodexSettings"];
            constraints: components["schemas"]["ConstraintsSettings"];
            /**
             * Default Adapter
             * @default auto
             * @enum {string}
             */
            default_adapter: "auto" | "claude_code" | "codex";
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** CodeAgentSettingsResponse */
        CodeAgentSettingsResponse: {
            settings: components["schemas"]["CodeAgentSettings"];
            /** Workspace Used */
            workspace_used: string | null;
        };
        /** CodexSettings */
        CodexSettings: {
            /**
             * Ask For Approval
             * @default never
             */
            ask_for_approval: string;
            /**
             * Binary Path
             * @default
             */
            binary_path: string;
            /**
             * Default Model
             * @default
             */
            default_model: string;
            /** Extra Args */
            extra_args: string[];
            /**
             * Sandbox
             * @default workspace-write
             */
            sandbox: string;
        };
        /** ConfigResponse */
        ConfigResponse: {
            /** @default null */
            data: components["schemas"]["SystemConfigModel"] | null;
            /** Message */
            message: string;
            /** Success */
            success: boolean;
        };
        /** ConstraintsSettings */
        ConstraintsSettings: {
            /**
             * Default Timeout S
             * @default 600
             */
            default_timeout_s: number;
            /**
             * Forbid Git Commit
             * @default true
             */
            forbid_git_commit: boolean;
            /**
             * Forbid Git Push
             * @default true
             */
            forbid_git_push: boolean;
            /** Forbid Paths */
            forbid_paths: string[];
        };
        /** CrossEncoderConfigModel */
        CrossEncoderConfigModel: {
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Managed Model Id
             * @default null
             */
            managed_model_id: string | null;
        };
        /** DiagnosticsConfigModel */
        DiagnosticsConfigModel: {
            /**
             * Full Content Logging Enabled
             * @default true
             */
            full_content_logging_enabled: boolean;
        };
        /**
         * DismissalKind
         * @description How the user dismissed a suggestion. Determines the TTL applied.
         * @enum {string}
         */
        DismissalKind: "transient" | "explicit" | "never";
        /** DismissalRecord */
        DismissalRecord: {
            /** Dedupe Key */
            dedupe_key: string;
            /**
             * Dismissed At
             * Format: date-time
             */
            dismissed_at: string;
            kind: components["schemas"]["DismissalKind"];
            /**
             * Title
             * @default null
             */
            title: string | null;
        };
        /** EmbeddingConfigModel */
        EmbeddingConfigModel: {
            local: components["schemas"]["EmbeddingLocalConfigModel"];
            /**
             * Mode
             * @default remote
             */
            mode: string;
        };
        /** EmbeddingLocalConfigModel */
        EmbeddingLocalConfigModel: {
            /**
             * Idle Timeout Seconds
             * @default 1800
             */
            idle_timeout_seconds: number;
            /**
             * Managed Model Id
             * @default null
             */
            managed_model_id: string | null;
            /**
             * Model Dir Path
             * @default null
             */
            model_dir_path: string | null;
            /**
             * Model Source
             * @default managed
             */
            model_source: string;
            /**
             * Variant
             * @default null
             */
            variant: string | null;
        };
        /** EntitySemanticEdgeConfigModel */
        EntitySemanticEdgeConfigModel: {
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
        };
        /** GraphSpreadingConfigModel */
        GraphSpreadingConfigModel: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** IdentityCoreModel */
        IdentityCoreModel: {
            /** Attention Biases */
            attention_biases: string[];
            /**
             * Identity Statement
             * @default
             */
            identity_statement: string;
            /** Values Loved */
            values_loved: string[];
            /** Values Rejected */
            values_rejected: string[];
        };
        /** IdiolectModel */
        IdiolectModel: {
            /**
             * Chattiness
             * @default 0.5
             */
            chattiness: number;
            /**
             * Sentence Style
             * @default
             */
            sentence_style: string;
            /** Structural Quirks */
            structural_quirks: string[];
            /** Vocab Available */
            vocab_available: string[];
            /** Vocab Avoided */
            vocab_avoided: string[];
        };
        /**
         * LLMCapabilitiesSettings
         * @description Declared capability flags for the active LLM.
         */
        LLMCapabilitiesSettings: {
            /**
             * Embedding
             * @default false
             */
            embedding: boolean;
            /**
             * Image Output
             * @default false
             */
            image_output: boolean;
            /**
             * Reasoning
             * @default true
             */
            reasoning: boolean;
            /**
             * Tool Calling
             * @default true
             */
            tool_calling: boolean;
            /**
             * Vision
             * @default false
             */
            vision: boolean;
        };
        /**
         * LLMCapabilityOverridesSettings
         * @description Per-model capability overrides applied on top of registry metadata.
         */
        LLMCapabilityOverridesSettings: {
            /**
             * Embedding
             * @default null
             */
            embedding: boolean | null;
            /**
             * Image Output
             * @default null
             */
            image_output: boolean | null;
            /**
             * Reasoning
             * @default null
             */
            reasoning: boolean | null;
            /**
             * Tool Calling
             * @default null
             */
            tool_calling: boolean | null;
            /**
             * Vision
             * @default null
             */
            vision: boolean | null;
        };
        /**
         * LLMConcurrencyOverrideSettings
         * @description Shared concurrency override for a concrete provider-model family.
         */
        LLMConcurrencyOverrideSettings: {
            /**
             * Max Concurrency
             * @default null
             */
            max_concurrency: number | null;
        };
        /** LLMConfigModel */
        LLMConfigModel: {
            /** Model Runtime Overrides */
            model_runtime_overrides: {
                [key: string]: components["schemas"]["LLMConcurrencyOverrideSettings"];
            };
            /** Providers */
            providers: {
                [key: string]: components["schemas"]["LLMProviderConfigModel"];
            };
            /** Selections */
            selections: {
                [key: string]: components["schemas"]["LLMSelectionConfigModel"];
            };
        };
        /**
         * LLMLimitsOverrideSettings
         * @description Per-model numeric limit overrides applied on top of registry metadata.
         */
        LLMLimitsOverrideSettings: {
            /**
             * Context Window
             * @default null
             */
            context_window: number | null;
            /**
             * Max Output Tokens
             * @default null
             */
            max_output_tokens: number | null;
            /**
             * Max Schema Tokens
             * @default null
             */
            max_schema_tokens: number | null;
            /**
             * Max Tool Schemas
             * @default null
             */
            max_tool_schemas: number | null;
        };
        /**
         * LLMModelCostModel
         * @description Provider-published pricing metadata for a model.
         */
        LLMModelCostModel: {
            /**
             * Cache Write Per Million Tokens
             * @default null
             */
            cache_write_per_million_tokens: number | null;
            /**
             * Cached Input Per Million Tokens
             * @default null
             */
            cached_input_per_million_tokens: number | null;
            /**
             * Currency
             * @default USD
             */
            currency: string;
            /**
             * Input Per Million Tokens
             * @default null
             */
            input_per_million_tokens: number | null;
            /**
             * Output Per Million Tokens
             * @default null
             */
            output_per_million_tokens: number | null;
            /**
             * Per Image
             * @default null
             */
            per_image: number | null;
            /**
             * Source
             * @default null
             */
            source: string | null;
            /**
             * Source Note
             * @default null
             */
            source_note: string | null;
        };
        /**
         * LLMModelMetadataOverrideSettings
         * @description User-defined metadata override for any provider model.
         */
        LLMModelMetadataOverrideSettings: {
            capabilities: components["schemas"]["LLMCapabilityOverridesSettings"];
            /** @default null */
            cost: components["schemas"]["LLMModelCostModel"] | null;
            /**
             * Description
             * @default null
             */
            description: string | null;
            /**
             * Dimensions
             * @default null
             */
            dimensions: number[] | null;
            /**
             * Hidden
             * @default null
             */
            hidden: boolean | null;
            /**
             * Icon
             * @default null
             */
            icon: string | null;
            /**
             * Input Modalities
             * @default null
             */
            input_modalities: string[] | null;
            /**
             * Label
             * @default null
             */
            label: string | null;
            limits: components["schemas"]["LLMLimitsOverrideSettings"];
            /**
             * Output Modalities
             * @default null
             */
            output_modalities: string[] | null;
            /**
             * Preferred
             * @default null
             */
            preferred: boolean | null;
            /**
             * Provider Options Example
             * @default null
             */
            provider_options_example: {
                [key: string]: unknown;
            } | null;
            /**
             * Source Note
             * @default null
             */
            source_note: string | null;
            /**
             * @description Behavioral vendor override. Set this on custom-gateway models (OneAPI etc.) so the runtime picks the correct reasoning / tool-calling payload shape rather than guessing from URL.
             * @default null
             */
            vendor: components["schemas"]["ModelVendor"] | null;
        };
        /** LLMProviderConfigModel */
        LLMProviderConfigModel: {
            /**
             * Api Format
             * @default null
             */
            api_format: string | null;
            /**
             * Api Key
             * @default null
             */
            api_key: string | null;
            /**
             * Base Url
             * @default null
             */
            base_url: string | null;
            /**
             * Custom Default Model
             * @default null
             */
            custom_default_model: string | null;
            /** Custom Models */
            custom_models: string[];
            /**
             * Display Name
             * @default OpenAI
             */
            display_name: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Model Metadata Overrides */
            model_metadata_overrides: {
                [key: string]: components["schemas"]["LLMModelMetadataOverrideSettings"];
            };
            /**
             * Provider Plan
             * @default null
             */
            provider_plan: string | null;
            /**
             * Provider Type
             * @default openai
             */
            provider_type: string;
            services: components["schemas"]["LLMProviderServicesConfigModel"];
        };
        /** LLMProviderConnectionConfigModel */
        LLMProviderConnectionConfigModel: {
            /**
             * Api Key
             * @default null
             */
            api_key: string | null;
            /**
             * Base Url
             * @default null
             */
            base_url: string | null;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** LLMProviderImageGenerationConfigModel */
        LLMProviderImageGenerationConfigModel: {
            /**
             * Api Key
             * @default null
             */
            api_key: string | null;
            /**
             * Base Url
             * @default null
             */
            base_url: string | null;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Native Protocol
             * @default null
             */
            native_protocol: string | null;
            /**
             * Timeout
             * @default 180
             */
            timeout: number;
        };
        /** LLMProviderServicesConfigModel */
        LLMProviderServicesConfigModel: {
            chat: components["schemas"]["LLMProviderConnectionConfigModel"];
            embedding: components["schemas"]["LLMProviderConnectionConfigModel"];
            image_generation: components["schemas"]["LLMProviderImageGenerationConfigModel"];
            tts: components["schemas"]["LLMProviderTTSConfigModel"];
        };
        /** LLMProviderTTSConfigModel */
        LLMProviderTTSConfigModel: {
            /**
             * Api Key
             * @default null
             */
            api_key: string | null;
            /**
             * Base Url
             * @default null
             */
            base_url: string | null;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Model
             * @default null
             */
            model: string | null;
            /**
             * Response Format
             * @default null
             */
            response_format: string | null;
            /**
             * Voice
             * @default null
             */
            voice: string | null;
        };
        /** LLMSelectionConfigModel */
        LLMSelectionConfigModel: {
            capabilities: components["schemas"]["LLMCapabilitiesSettings"];
            /**
             * Capability Override Enabled
             * @default false
             */
            capability_override_enabled: boolean;
            /**
             * Embedding Dimension
             * @default null
             */
            embedding_dimension: number | null;
            limits: components["schemas"]["LLMSelectionLimitsSettings"];
            /**
             * Model
             * @default
             */
            model: string;
            /**
             * Provider Id
             * @default
             */
            provider_id: string;
            /** Provider Options */
            provider_options: {
                [key: string]: unknown;
            };
        };
        /**
         * LLMSelectionLimitsSettings
         * @description Per-scenario numeric limits that remain local to scenario selection.
         */
        LLMSelectionLimitsSettings: {
            /**
             * Context Window
             * @default null
             */
            context_window: number | null;
            /**
             * Max Output Tokens
             * @default null
             */
            max_output_tokens: number | null;
            /**
             * Max Schema Tokens
             * @default null
             */
            max_schema_tokens: number | null;
            /**
             * Max Tool Schemas
             * @default null
             */
            max_tool_schemas: number | null;
        };
        LayerModifiersModel: {
            [key: string]: unknown;
        };
        /** MemoryConfigModel */
        MemoryConfigModel: {
            /** Archive Path */
            archive_path: string | null;
            /** Db Path */
            db_path: string | null;
            embedding: components["schemas"]["EmbeddingConfigModel"];
            entity_semantic_edges: components["schemas"]["EntitySemanticEdgeConfigModel"];
            graph_spreading: components["schemas"]["GraphSpreadingConfigModel"];
            /**
             * History Behavior
             * @default delete
             */
            history_behavior: string;
            l0: components["schemas"]["MemoryL0ConfigModel"];
            l1: components["schemas"]["MemoryL1ConfigModel"];
            l2: components["schemas"]["MemoryL2ConfigModel"];
            l3: components["schemas"]["MemoryL3ConfigModel"];
            l4: components["schemas"]["MemoryL4ConfigModel"];
            query_expansion: components["schemas"]["QueryExpansionConfigModel"];
            reranker: components["schemas"]["MemoryRerankerConfigModel"];
            /**
             * Retention Days
             * @default 90
             */
            retention_days: number;
        };
        /** MemoryL0ConfigModel */
        MemoryL0ConfigModel: {
            /**
             * Attention Update Idle Seconds
             * @default 30
             */
            attention_update_idle_seconds: number;
            /**
             * Attention Update Max Delay Seconds
             * @default 90
             */
            attention_update_max_delay_seconds: number;
            /**
             * Attention Update Turn Threshold
             * @default 3
             */
            attention_update_turn_threshold: number;
            /**
             * Checkpoint Interval Seconds
             * @default 30
             */
            checkpoint_interval_seconds: number;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** MemoryL1ConfigModel */
        MemoryL1ConfigModel: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Retention Days
             * @default 30
             */
            retention_days: number;
            /**
             * Vectors Enabled
             * @default true
             */
            vectors_enabled: boolean;
        };
        /** MemoryL2ConfigModel */
        MemoryL2ConfigModel: {
            /**
             * Auto Extract Relations
             * @default true
             */
            auto_extract_relations: boolean;
            /**
             * Batch Flush Interval Seconds
             * @default 60
             */
            batch_flush_interval_seconds: number;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Portrait Projection Refresh Delay Seconds
             * @default 120
             */
            portrait_projection_refresh_delay_seconds: number;
            /**
             * Shadow Conflict Notification Enabled
             * @default true
             */
            shadow_conflict_notification_enabled: boolean;
            /**
             * Vectors Enabled
             * @default true
             */
            vectors_enabled: boolean;
        };
        /** MemoryL3ConfigModel */
        MemoryL3ConfigModel: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Llm Summary Enabled
             * @default true
             */
            llm_summary_enabled: boolean;
            /**
             * Retention Days
             * @default 180
             */
            retention_days: number;
            /**
             * Temporal Llm Min Event Count
             * @default 2
             */
            temporal_llm_min_event_count: number;
            /**
             * Temporal Llm Timeout Seconds
             * @default 3
             */
            temporal_llm_timeout_seconds: number;
            /**
             * Vectors Enabled
             * @default true
             */
            vectors_enabled: boolean;
        };
        /** MemoryL4ConfigModel */
        MemoryL4ConfigModel: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Inactive Skill Min Attempts
             * @default 5
             */
            inactive_skill_min_attempts: number;
            /**
             * Inactive Skill Retention Days
             * @default 30
             */
            inactive_skill_retention_days: number;
            /**
             * Vectors Enabled
             * @default true
             */
            vectors_enabled: boolean;
        };
        /** MemoryRerankerConfigModel */
        MemoryRerankerConfigModel: {
            cross_encoder: components["schemas"]["CrossEncoderConfigModel"];
            /**
             * Top K
             * @default 8
             */
            top_k: number;
        };
        /**
         * ModelVendor
         * @description The behavioral vendor a model belongs to.
         *
         *     ``provider`` is *who hosts the endpoint* (which can be an OneAPI-style
         *     gateway). ``vendor`` is *who built the model* and therefore decides
         *     payload shape: how reasoning is expressed, how tool-calling is
         *     serialized, where system prompts live, etc.
         *
         *     A single OneAPI gateway may proxy ``glm-4-plus`` (vendor=GLM),
         *     ``qwen-max`` (vendor=DASHSCOPE), and ``claude-sonnet-4-6``
         *     (vendor=ANTHROPIC) under the same ``provider``. Routing dialects off
         *     provider name would misroute each of these; routing off vendor is
         *     correct.
         *
         *     ``GENERIC`` means "OpenAI-compatible transport, no vendor-specific
         *     extensions"; reasoning / thinking knobs are not injected.
         * @enum {string}
         */
        ModelVendor: "openai" | "deepseek" | "anthropic" | "glm" | "dashscope" | "grok" | "gemini" | "kimi" | "minimax" | "generic";
        /** NetworkProxyConfigModel */
        NetworkProxyConfigModel: {
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Host
             * @default 127.0.0.1
             */
            host: string;
            /**
             * Password
             * @default
             */
            password: string;
            /**
             * Port
             * @default 7890
             */
            port: number;
            /**
             * Proxy Type
             * @default http
             */
            proxy_type: string;
            /**
             * Username
             * @default
             */
            username: string;
        };
        /** OnboardingStatusDataModel */
        OnboardingStatusDataModel: {
            /** Completed */
            completed: boolean;
        };
        /** OnboardingStatusResponse */
        OnboardingStatusResponse: {
            data: components["schemas"]["OnboardingStatusDataModel"];
            /** Message */
            message: string;
            /** Success */
            success: boolean;
        };
        /** OnboardingTemplateDataModel */
        OnboardingTemplateDataModel: {
            config: components["schemas"]["SystemConfigModel"];
        };
        /** OnboardingTemplateResponse */
        OnboardingTemplateResponse: {
            /** @default null */
            data: components["schemas"]["OnboardingTemplateDataModel"] | null;
            /** Message */
            message: string;
            /** Success */
            success: boolean;
        };
        /** PersonaLayerModel */
        PersonaLayerModel: {
            /**
             * Layer Id
             * @default
             */
            layer_id: string;
            modifiers: components["schemas"]["LayerModifiersModel"];
            /**
             * Unlock Condition
             * @default null
             */
            unlock_condition: {
                [key: string]: unknown;
            } | null;
        };
        /** PersonalityConfigModel */
        PersonalityConfigModel: {
            /**
             * Appearance Prompt
             * @default
             */
            appearance_prompt: string;
            /**
             * Avatar
             * @default
             */
            avatar: string;
            /** @default null */
            bootstrap: components["schemas"]["BootstrapConfigModel"] | null;
            /**
             * Description
             * @default
             */
            description: string;
            /** Dynamic State Rules */
            dynamic_state_rules: {
                [key: string]: string;
            };
            identity_core: components["schemas"]["IdentityCoreModel"];
            idiolect: components["schemas"]["IdiolectModel"];
            /** Interim Lines */
            interim_lines: {
                [key: string]: string[];
            };
            /** Milestone Conditions */
            milestone_conditions: {
                [key: string]: string;
            };
            /**
             * Name
             * @default AI Assistant
             */
            name: string;
            /** Persona Layers */
            persona_layers: components["schemas"]["PersonaLayerModel"][];
            /** Quiet Hours */
            quiet_hours: components["schemas"]["QuietHourModel"][];
            /** Registers */
            registers: {
                [key: string]: components["schemas"]["RegisterModel"];
            };
            /** Signature Triggers */
            signature_triggers: components["schemas"]["SignatureTriggerModel"][];
        };
        /** PersonalitySettingsModel */
        PersonalitySettingsModel: {
            /**
             * Deep Persona Enabled
             * @default true
             */
            deep_persona_enabled: boolean;
            /**
             * State Memory Enabled
             * @default true
             */
            state_memory_enabled: boolean;
            /**
             * State Transition Enabled
             * @default true
             */
            state_transition_enabled: boolean;
        };
        /** ProbeResult */
        ProbeResult: {
            /** Binary Path */
            binary_path: string | null;
            /** Detected At */
            detected_at: number;
            /** Error */
            error: string | null;
            /** Extras */
            extras: {
                [key: string]: unknown;
            };
            /** Installed */
            installed: boolean;
            /**
             * Name
             * @enum {string}
             */
            name: "claude_code" | "codex";
            /** Version */
            version: string | null;
        };
        /** QueryExpansionConfigModel */
        QueryExpansionConfigModel: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Max Expansions
             * @default 2
             */
            max_expansions: number;
        };
        /** QuietHourModel */
        QuietHourModel: {
            /** Clamps */
            clamps: {
                [key: string]: unknown;
            };
            /**
             * Condition
             * @default
             */
            condition: string;
        };
        /** RegisterModel */
        RegisterModel: {
            /**
             * Behavior
             * @default
             */
            behavior: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** Examples */
            examples: string[];
        };
        /** SignatureTriggerModel */
        SignatureTriggerModel: {
            /**
             * Activates When
             * @default
             */
            activates_when: string;
            /**
             * Behavior Shift
             * @default
             */
            behavior_shift: string;
            /**
             * Exit Behavior
             * @default
             */
            exit_behavior: string;
            /** Intensity Levels */
            intensity_levels: {
                [key: string]: string;
            };
            /**
             * Trigger Id
             * @default
             */
            trigger_id: string;
        };
        /** SystemConfigModel */
        SystemConfigModel: {
            agent: components["schemas"]["AgentConfigModel"];
            diagnostics: components["schemas"]["DiagnosticsConfigModel"];
            llm: components["schemas"]["LLMConfigModel"];
            memory: components["schemas"]["MemoryConfigModel"];
            network: components["schemas"]["NetworkProxyConfigModel"];
            personality: components["schemas"]["PersonalityConfigModel"];
            personalitySettings: components["schemas"]["PersonalitySettingsModel"];
            preferences: components["schemas"]["UserPreferencesModel"];
            /** Skills */
            skills: string[];
            timeline: components["schemas"]["TimelineConfigModel"];
        };
        /** TimelineConfigModel */
        TimelineConfigModel: {
            sources: components["schemas"]["TimelineSourcesConfigModel"];
        };
        /** TimelineSourceConfigModel */
        TimelineSourceConfigModel: {
            /**
             * Default Retention Mode
             * @default analyze_only
             */
            default_retention_mode: string;
            /** Edge Whitelist */
            edge_whitelist: string[];
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Fetch Page Content
             * @default false
             */
            fetch_page_content: boolean;
            /**
             * Source Path
             * @default null
             */
            source_path: string | null;
            /**
             * Storage Mode
             * @default managed
             */
            storage_mode: string;
            /**
             * Sync Interval Minutes
             * @default 15
             */
            sync_interval_minutes: number;
            /**
             * Sync Mode
             * @default interval
             */
            sync_mode: string;
        };
        /** TimelineSourcesConfigModel */
        TimelineSourcesConfigModel: {
            /** @default null */
            calendar: components["schemas"]["TimelineSourceConfigModel"] | null;
            /** @default null */
            chrome_history: components["schemas"]["TimelineSourceConfigModel"] | null;
            /** @default null */
            git_activity: components["schemas"]["TimelineSourceConfigModel"] | null;
            /** @default null */
            netease_music: components["schemas"]["TimelineSourceConfigModel"] | null;
            photo_library: components["schemas"]["TimelineSourceConfigModel"];
            /** @default null */
            screen_time: components["schemas"]["TimelineSourceConfigModel"] | null;
            /** @default null */
            terminal_history: components["schemas"]["TimelineSourceConfigModel"] | null;
        };
        /**
         * ToolConfigResponse
         * @description Tool configuration response
         */
        ToolConfigResponse: {
            /**
             * Category
             * @description Tool category
             */
            category: string;
            /**
             * Config Specs
             * @description Config specifications
             */
            config_specs: components["schemas"]["ToolConfigSpecResponse"][];
            /**
             * Current Values
             * @description Current config values (non-sensitive)
             */
            current_values: {
                [key: string]: unknown;
            };
            /**
             * Description
             * @description Tool description
             */
            description: string;
            /**
             * Display Name
             * @description Human-readable tool name
             */
            display_name: string;
            /**
             * Enabled
             * @description Whether tool is enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Is Multi Provider
             * @description Whether this is a multi-provider tool
             * @default false
             */
            is_multi_provider: boolean;
            /**
             * Is Ready
             * @description Whether tool is configured and ready
             * @default true
             */
            is_ready: boolean;
            /**
             * Name
             * @description Tool name
             */
            name: string;
            /**
             * Providers
             * @description Available providers
             */
            providers: components["schemas"]["ToolProviderInfo"][];
            /**
             * Version
             * @description Tool version
             * @default 1.0.0
             */
            version: string;
        };
        /**
         * ToolConfigSpecResponse
         * @description Tool config spec for API response
         */
        ToolConfigSpecResponse: {
            /**
             * Default
             * @description Default value
             * @default null
             */
            default: unknown | null;
            /**
             * Description
             * @description Config item description
             * @default
             */
            description: string;
            /**
             * Enum
             * @description Enum values for selection
             * @default null
             */
            enum: unknown[] | null;
            /**
             * Is Template
             * @description Whether this is a template path (e.g., providers.{provider}.api_key)
             * @default false
             */
            is_template: boolean;
            /**
             * Path
             * @description Config path (relative to tool namespace)
             */
            path: string;
            /**
             * Placeholder
             * @description Input placeholder hint
             * @default null
             */
            placeholder: string | null;
            /**
             * Providers
             * @description Providers that this spec applies to
             * @default null
             */
            providers: string[] | null;
            /**
             * Read Only
             * @description Cannot be changed
             * @default false
             */
            read_only: boolean;
            /**
             * Required
             * @description Whether this config is required
             * @default false
             */
            required: boolean;
            /**
             * Sensitive
             * @description Can be set but not read
             * @default false
             */
            sensitive: boolean;
            /**
             * Type
             * @description Config value type
             * @default string
             * @enum {string}
             */
            type: "string" | "integer" | "float" | "boolean" | "array" | "object";
        };
        /**
         * ToolProviderInfo
         * @description Provider information for multi-provider tools
         */
        ToolProviderInfo: {
            /**
             * Display Name
             * @description Human-readable provider name
             */
            display_name: string;
            /**
             * Is Ready
             * @description Whether provider is configured and ready
             */
            is_ready: boolean;
            /**
             * Name
             * @description Provider identifier
             */
            name: string;
            /**
             * Required Config
             * @description Required config paths
             */
            required_config: string[];
        };
        /**
         * ToolsListResponse
         * @description Tools list response with config info
         */
        ToolsListResponse: {
            /**
             * Tools
             * @description List of tools with config info
             */
            tools: components["schemas"]["ToolConfigResponse"][];
            /**
             * Total
             * @description Total number of tools
             */
            total: number;
        };
        /** UserPreferencesModel */
        UserPreferencesModel: {
            /**
             * Allow Ask In Background
             * @default false
             */
            allow_ask_in_background: boolean;
            /**
             * Allow Interjection
             * @default false
             */
            allow_interjection: boolean;
            /**
             * Allow Media Grounding For Conversation
             * @default true
             */
            allow_media_grounding_for_conversation: boolean;
            /**
             * Conversation Rhythm Enabled
             * @default true
             */
            conversation_rhythm_enabled: boolean;
            /**
             * Conversation Rhythm Mode
             * @default natural
             */
            conversation_rhythm_mode: string;
            /** Default Chat Workspace Path */
            default_chat_workspace_path: string | null;
            /**
             * First Conversation Completed
             * @description Legacy onboarding state retained for existing saved preferences. The chat UI no longer uses it to show starter prompts.
             * @default false
             */
            first_conversation_completed: boolean;
            /**
             * Language
             * @default zh
             */
            language: string;
            /**
             * Onboarding Completed
             * @default false
             */
            onboarding_completed: boolean;
            /**
             * Product Tour Completed
             * @description True once the user has completed (or skipped) the one-time main-page product tour shown on first visit after onboarding.
             * @default false
             */
            product_tour_completed: boolean;
            /**
             * Scenario
             * @default null
             */
            scenario: string | null;
            /**
             * Streaming Chat Enabled
             * @default false
             */
            streaming_chat_enabled: boolean;
            /**
             * Suggestion Dismissals
             * @description Map of dedupe_key → DismissalRecord. The signal matcher filters out any candidate whose dedupe_key appears here and whose TTL (based on kind) has not yet expired.
             */
            suggestion_dismissals: {
                [key: string]: components["schemas"]["DismissalRecord"];
            };
            /**
             * User Mode
             * @default null
             */
            user_mode: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export type operations = Record<string, never>;
