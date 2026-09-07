// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ActivationFirstContextSpec
         * @description First-run-only activation settings applied by the host onboarding UI.
         */
        ActivationFirstContextSpec: {
            /**
             * Max Items Per Sync
             * @default null
             */
            max_items_per_sync: number | null;
            /** Settings Overrides */
            settings_overrides: {
                [key: string]: unknown;
            };
        };
        /** ActivationFlowResponse */
        ActivationFlowResponse: {
            /**
             * Authorize On Confirm
             * @default false
             */
            authorize_on_confirm: boolean;
            /**
             * Cancel Label
             * @default Cancel
             */
            cancel_label: string;
            /**
             * Cancel Label Translated
             * @default null
             */
            cancel_label_translated: string | null;
            /** Configured Key */
            configured_key: string;
            /**
             * Confirm Label
             * @default Confirm
             */
            confirm_label: string;
            /**
             * Confirm Label Translated
             * @default null
             */
            confirm_label_translated: string | null;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Description Translated
             * @default null
             */
            description_translated: string | null;
            /** Enabled Key */
            enabled_key: string;
            /** Fields */
            fields: components["schemas"]["ExtensionFieldResponse"][];
            /** @default null */
            first_context: components["schemas"]["ActivationFirstContextSpec"] | null;
            /** Title */
            title: string;
            /**
             * Title Translated
             * @default null
             */
            title_translated: string | null;
        };
        /**
         * ActivationFlowSpec
         * @description Declarative first-enable flow rendered by the host UI.
         */
        ActivationFlowSpec: {
            /**
             * Authorize On Confirm
             * @default false
             */
            authorize_on_confirm: boolean;
            /**
             * Cancel Label
             * @default Cancel
             */
            cancel_label: string;
            /** Configured Key */
            configured_key: string;
            /**
             * Confirm Label
             * @default Confirm
             */
            confirm_label: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** Enabled Key */
            enabled_key: string;
            /** Fields */
            fields: components["schemas"]["ExtensionFieldSpec"][];
            /** @default null */
            first_context: components["schemas"]["ActivationFirstContextSpec"] | null;
            /** Title */
            title: string;
        };
        /**
         * CapabilityReadiness
         * @description One authoritative capability state shared by UI and execution admission.
         */
        CapabilityReadiness: {
            /** Capability Id */
            capability_id: string;
            /** Connection Id */
            connection_id: string;
            /**
             * Message
             * @default null
             */
            message: string | null;
            /**
             * Reason Code
             * @default null
             */
            reason_code: string | null;
            status: components["schemas"]["ConnectionStatus"];
        };
        /**
         * ConnectionStatus
         * @enum {string}
         */
        ConnectionStatus: "disabled" | "setup_required" | "auth_required" | "ready" | "degraded" | "failed";
        /**
         * ContributionType
         * @description Supported plugin contribution categories.
         * @enum {string}
         */
        ContributionType: "operation" | "provider" | "tool" | "source" | "channel" | "skill" | "hook" | "history_importer";
        /**
         * ExtensionFieldOption
         * @description Option for a select-like plugin field.
         */
        ExtensionFieldOption: {
            /** Label */
            label: string;
            /** Value */
            value: string;
        };
        /** ExtensionFieldOptionResponse */
        ExtensionFieldOptionResponse: {
            /** Label */
            label: string;
            /**
             * Label Translated
             * @default null
             */
            label_translated: string | null;
            /** Value */
            value: string;
        };
        /**
         * ExtensionFieldResponse
         * @description Host-rendered plugin field, including translated presentation metadata.
         */
        ExtensionFieldResponse: {
            /**
             * Default
             * @default null
             */
            default: unknown;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Description Translated
             * @default null
             */
            description_translated: string | null;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /**
             * Label Translated
             * @default null
             */
            label_translated: string | null;
            /**
             * Maximum
             * @default null
             */
            maximum: number | null;
            /**
             * Minimum
             * @default null
             */
            minimum: number | null;
            /** Options */
            options: components["schemas"]["ExtensionFieldOptionResponse"][];
            /**
             * Order
             * @default 0
             */
            order: number;
            /**
             * Path Kind
             * @default null
             */
            path_kind: ("file" | "directory") | null;
            /**
             * Placeholder
             * @default null
             */
            placeholder: string | null;
            /**
             * Required
             * @default false
             */
            required: boolean;
            /**
             * Section
             * @default general
             */
            section: string;
            /**
             * Section Note Translated
             * @default null
             */
            section_note_translated: string | null;
            /**
             * Section Translated
             * @default null
             */
            section_translated: string | null;
            /**
             * Surface
             * @default extensions
             * @enum {string}
             */
            surface: "extensions" | "tools" | "timeline";
            /**
             * Type
             * @default input
             * @enum {string}
             */
            type: "switch" | "select" | "input" | "number" | "secret" | "path" | "tags";
        };
        /**
         * ExtensionFieldSpec
         * @description Declarative settings field exposed by a plugin contribution.
         */
        ExtensionFieldSpec: {
            /**
             * Default
             * @default null
             */
            default: unknown;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /**
             * Maximum
             * @default null
             */
            maximum: number | null;
            /**
             * Minimum
             * @default null
             */
            minimum: number | null;
            /** Options */
            options: components["schemas"]["ExtensionFieldOption"][];
            /**
             * Order
             * @default 0
             */
            order: number;
            /**
             * Path Kind
             * @default null
             */
            path_kind: ("file" | "directory") | null;
            /**
             * Placeholder
             * @default null
             */
            placeholder: string | null;
            /**
             * Required
             * @default false
             */
            required: boolean;
            /**
             * Section
             * @default general
             */
            section: string;
            /**
             * Surface
             * @default extensions
             * @enum {string}
             */
            surface: "extensions" | "tools" | "timeline";
            /**
             * Type
             * @default input
             * @enum {string}
             */
            type: "switch" | "select" | "input" | "number" | "secret" | "path" | "tags";
        };
        JsonValue: unknown;
        /**
         * LocalRequirementAppInstalled
         * @description Requires an application identified by a platform-native identifier to be installed.
         */
        LocalRequirementAppInstalled: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            check_kind: "app_installed";
            /** Identifier Per Platform */
            identifier_per_platform: {
                [key: string]: string;
            };
        };
        /**
         * LocalRequirementExecutableInPath
         * @description Requires at least one named executable to be reachable via PATH.
         */
        LocalRequirementExecutableInPath: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            check_kind: "executable_in_path";
            /** Names */
            names: string[];
        };
        /**
         * LocalRequirementFileExists
         * @description Requires a file to exist at the platform-specific path.
         */
        LocalRequirementFileExists: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            check_kind: "file_exists";
            /** Paths Per Platform */
            paths_per_platform: {
                [key: string]: string;
            };
        };
        /**
         * LocalizedText
         * @description Per-locale strings; both zh and en are required.
         */
        LocalizedText: {
            /** En */
            en: string;
            /** Zh */
            zh: string;
        };
        /**
         * PluginCapability
         * @description A requested capability, never a grant of runtime authority.
         *
         *     The host authorizes access for a connection separately. Unknown operations
         *     cannot become executable merely by appearing in a package declaration.
         *     The publication policy validates the supported set: screen_recording,
         *     accessibility, calendar, photos, contacts, system_media, filesystem_read,
         *     filesystem_write, network, subprocess, memory_search, interaction_ask.
         *     Public host services require the exact current_user (memory_search) or
         *     current_session (interaction_ask) scope and separate invocation admission.
         */
        PluginCapability: {
            /** Capability */
            capability: string;
            /**
             * Optional
             * @default false
             */
            optional: boolean;
            /**
             * Reason
             * @default
             */
            reason: string;
            /** Reason I18N */
            reason_i18n: {
                [key: string]: string;
            };
            /** Scope */
            scope: string[];
        };
        /** PluginConnectionResponse */
        PluginConnectionResponse: {
            /** Connection Id */
            connection_id: string;
            /** Credential Refs */
            credential_refs: {
                [key: string]: string;
            };
            /** Display Name */
            display_name: string;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /** Plugin Id */
            plugin_id: string;
            /** Readiness */
            readiness: components["schemas"]["CapabilityReadiness"][];
            /**
             * Revision
             * @default 0
             */
            revision: number;
            /** Settings */
            settings: {
                [key: string]: components["schemas"]["JsonValue"];
            };
        };
        /** PluginConnectionsResponse */
        PluginConnectionsResponse: {
            /** Connections */
            connections: components["schemas"]["PluginConnectionResponse"][];
            /** Total */
            total: number;
        };
        /** PluginContributionResponse */
        PluginContributionResponse: {
            /** Contribution Id */
            contribution_id: string;
            /** Contribution Type */
            contribution_type: string;
            /** Description */
            description: string;
            /** Display Name */
            display_name: string;
            /** Fields */
            fields: components["schemas"]["ExtensionFieldResponse"][];
            /** Metadata */
            metadata: {
                [key: string]: unknown;
            };
            /** Plugin Id */
            plugin_id: string;
            /**
             * Surface
             * @enum {string}
             */
            surface: "extensions" | "tools" | "timeline";
        };
        /**
         * PluginDisplayGroupSpec
         * @description User-facing grouping metadata for marketplace and installed plugin UIs.
         */
        PluginDisplayGroupSpec: {
            /**
             * Description
             * @default
             */
            description: string;
            /** Description I18N */
            description_i18n: {
                [key: string]: string;
            };
            /**
             * Icon
             * @default
             */
            icon: string;
            /** Id */
            id: string;
            /**
             * Member Label
             * @default
             */
            member_label: string;
            /** Member Label I18N */
            member_label_i18n: {
                [key: string]: string;
            };
            /**
             * Member Order
             * @default 100
             */
            member_order: number;
            /** Name */
            name: string;
            /** Name I18N */
            name_i18n: {
                [key: string]: string;
            };
            /**
             * Order
             * @default 100
             */
            order: number;
        };
        /** PluginInstallCandidateResponse */
        PluginInstallCandidateResponse: {
            /** Archive Sha256 */
            archive_sha256: string;
            /** Candidate Id */
            candidate_id: string;
            /** Expires At Ms */
            expires_at_ms: number;
            manifest: components["schemas"]["PluginManifestResponse"];
            /** Package Sha256 */
            package_sha256: string;
        };
        /** PluginInstallJobSnapshot */
        PluginInstallJobSnapshot: {
            /** Created At Ms */
            created_at_ms: number;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Error Code
             * @default null
             */
            error_code: string | null;
            /**
             * Filename
             * @default null
             */
            filename: string | null;
            /**
             * Finished At Ms
             * @default null
             */
            finished_at_ms: number | null;
            /** Job Id */
            job_id: string;
            /** Logs */
            logs: components["schemas"]["PluginInstallLogEntry"][];
            /** Message */
            message: string;
            /**
             * Operation
             * @enum {string}
             */
            operation: "install" | "update" | "upload";
            /**
             * Plugin Id
             * @default null
             */
            plugin_id: string | null;
            /**
             * Progress Pct
             * @default 0
             */
            progress_pct: number;
            /** @default null */
            result: components["schemas"]["PluginPackageResponse"] | null;
            /** Stage */
            stage: string;
            /**
             * Status
             * @enum {string}
             */
            status: "queued" | "running" | "completed" | "failed";
            /** Updated At Ms */
            updated_at_ms: number;
        };
        /** PluginInstallLogEntry */
        PluginInstallLogEntry: {
            /**
             * Level
             * @default info
             * @enum {string}
             */
            level: "info" | "warning" | "error";
            /** Message */
            message: string;
            /** Stage */
            stage: string;
            /** Ts Ms */
            ts_ms: number;
        };
        /** PluginInstallPlanChangeResponse */
        PluginInstallPlanChangeResponse: {
            /**
             * Action
             * @enum {string}
             */
            action: "install" | "update" | "reuse";
            /** Current Dependency Package Sha256 */
            current_dependency_package_sha256: {
                [key: string]: string;
            };
            /** Current Installed Package Sha256 */
            current_installed_package_sha256: string | null;
            /** Current Package Sha256 */
            current_package_sha256: string | null;
            /** Current Version */
            current_version: string | null;
            /** Dependency Package Sha256 */
            dependency_package_sha256: {
                [key: string]: string;
            };
            entry: components["schemas"]["PluginRegistryEntry"];
            /** Reason */
            reason: string;
        };
        /** PluginInstallPlanRequest */
        PluginInstallPlanRequest: {
            /** Plugin Id */
            plugin_id: string;
            /** Update */
            update: boolean;
        };
        /** PluginInstallPlanResponse */
        PluginInstallPlanResponse: {
            /** Changes */
            changes: components["schemas"]["PluginInstallPlanChangeResponse"][];
            /** Coordinated */
            coordinated: boolean;
            /** Fingerprint */
            fingerprint: string;
            /**
             * Format
             * @constant
             */
            format: "registry-install-plan-v1";
            /** Registry Fingerprint */
            registry_fingerprint: string;
            /** Target Id */
            target_id: string;
            /** Update */
            update: boolean;
        };
        /** PluginInstallRequest */
        PluginInstallRequest: {
            /** Plan Fingerprint */
            plan_fingerprint: string;
            /** Plugin Id */
            plugin_id: string;
        };
        /** PluginManifestResponse */
        PluginManifestResponse: {
            /** @default null */
            activation_flow: components["schemas"]["ActivationFlowResponse"] | null;
            /** Author */
            author: string;
            /** Capabilities */
            capabilities: components["schemas"]["PluginCapability"][];
            /**
             * Consented Capabilities
             * @default null
             */
            consented_capabilities: components["schemas"]["PluginCapability"][] | null;
            /** Contribution Types */
            contribution_types: string[];
            /** Description */
            description: string;
            /** @default null */
            display_group: components["schemas"]["PluginDisplayGroupSpec"] | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode: "restricted_process" | "trusted_process";
            /**
             * Icon
             * @default
             */
            icon: string;
            /** Manifest Path */
            manifest_path: string;
            /** Min Sdk Version */
            min_sdk_version: string;
            /** Name */
            name: string;
            /** Official */
            official: boolean;
            /** Plugin Dir */
            plugin_dir: string;
            /** Plugin Id */
            plugin_id: string;
            /**
             * Protocol Version
             * @constant
             */
            protocol_version: 2;
            /** Settings Actions */
            settings_actions: components["schemas"]["PluginSettingsActionResponse"][];
            /** Settings Fields */
            settings_fields: components["schemas"]["ExtensionFieldResponse"][];
            /** Settings Resources */
            settings_resources: components["schemas"]["PluginSettingsResourceSpec"][];
            /** Settings Ui Blocks */
            settings_ui_blocks: components["schemas"]["PluginSettingsUiBlockResponse"][];
            /** Source */
            source: string;
            /** Version */
            version: string;
        };
        /** PluginPackageResponse */
        PluginPackageResponse: {
            /** Contributions */
            contributions: components["schemas"]["PluginContributionResponse"][];
            /** Current Settings */
            current_settings: {
                [key: string]: unknown;
            };
            /** Enabled */
            enabled: boolean;
            /** Healthy */
            healthy: boolean;
            /**
             * Last Error
             * @default null
             */
            last_error: string | null;
            /** Loaded */
            loaded: boolean;
            manifest: components["schemas"]["PluginManifestResponse"];
            /**
             * Package Sha256
             * @default null
             */
            package_sha256: string | null;
            /** Trusted */
            trusted: boolean;
        };
        /** PluginRegistryApprovalRequest */
        PluginRegistryApprovalRequest: {
            /** Plan Fingerprint */
            plan_fingerprint: string;
        };
        /**
         * PluginRegistryEntry
         * @description Remote plugin registry entry describing an available plugin.
         */
        PluginRegistryEntry: {
            /** @default null */
            activation_flow: components["schemas"]["ActivationFlowSpec"] | null;
            /**
             * Author
             * @default
             */
            author: string;
            /** Capabilities */
            capabilities: components["schemas"]["PluginCapability"][];
            /** Contribution Types */
            contribution_types: string[];
            /**
             * Data Locality
             * @default
             */
            data_locality: string;
            /** Depends On */
            depends_on: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /** Description I18N */
            description_i18n: {
                [key: string]: string;
            };
            /** @default null */
            display_group: components["schemas"]["PluginDisplayGroupSpec"] | null;
            /**
             * Execution Mode
             * @default restricted_process
             * @enum {string}
             */
            execution_mode: "restricted_process" | "trusted_process";
            /**
             * Homepage
             * @default
             */
            homepage: string;
            /**
             * Icon
             * @default
             */
            icon: string;
            /**
             * Icon Data
             * @default
             */
            icon_data: string;
            /**
             * Kind
             * @default plugin
             * @enum {string}
             */
            kind: "plugin" | "library";
            /**
             * Min Sdk Version
             * @default 0.2.1
             */
            min_sdk_version: string;
            /** Name */
            name: string;
            /** Name I18N */
            name_i18n: {
                [key: string]: string;
            };
            /**
             * Official
             * @default false
             */
            official: boolean;
            /**
             * Package Sha256
             * @description Host-verified digest of the complete distributable plugin package.
             */
            package_sha256: string;
            /**
             * Path
             * @default
             */
            path: string;
            /** Platforms */
            platforms: string[];
            /** Plugin Id */
            plugin_id: string;
            /** Projection Sources */
            projection_sources: string[];
            /**
             * Protocol Version
             * @default 2
             * @constant
             */
            protocol_version: 2;
            /**
             * Repository
             * @default
             */
            repository: string;
            /** Settings Actions */
            settings_actions: components["schemas"]["PluginSettingsActionSpec"][];
            /** Settings Fields */
            settings_fields: components["schemas"]["ExtensionFieldSpec"][];
            /** Settings Resources */
            settings_resources: components["schemas"]["PluginSettingsResourceSpec"][];
            /** Settings Ui Blocks */
            settings_ui_blocks: components["schemas"]["SettingsUIBlockSpec"][];
            /** @default null */
            suggestion_descriptor: components["schemas"]["SuggestionDescriptor"] | null;
            /** Version */
            version: string;
        };
        /** PluginRegistryEntryResponse */
        PluginRegistryEntryResponse: {
            /** @default null */
            activation_flow: components["schemas"]["ActivationFlowSpec"] | null;
            /**
             * Author
             * @default
             */
            author: string;
            /** Capabilities */
            capabilities: components["schemas"]["PluginCapability"][];
            /** Contribution Types */
            contribution_types: string[];
            /**
             * Data Locality
             * @default
             */
            data_locality: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** Description I18N */
            description_i18n: {
                [key: string]: string;
            };
            /** @default null */
            display_group: components["schemas"]["PluginDisplayGroupSpec"] | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode: "restricted_process" | "trusted_process";
            /**
             * Homepage
             * @default
             */
            homepage: string;
            /**
             * Icon
             * @default
             */
            icon: string;
            /**
             * Installed
             * @default false
             */
            installed: boolean;
            /**
             * Installed Version
             * @default null
             */
            installed_version: string | null;
            /** Min Sdk Version */
            min_sdk_version: string;
            /** Name */
            name: string;
            /** Name I18N */
            name_i18n: {
                [key: string]: string;
            };
            /**
             * Official
             * @default false
             */
            official: boolean;
            /**
             * Path
             * @default
             */
            path: string;
            /** Platforms */
            platforms: string[];
            /** Plugin Id */
            plugin_id: string;
            /**
             * Protocol Version
             * @constant
             */
            protocol_version: 2;
            /**
             * Repository
             * @default
             */
            repository: string;
            /** Settings Actions */
            settings_actions: components["schemas"]["PluginSettingsActionSpec"][];
            /** Settings Fields */
            settings_fields: components["schemas"]["ExtensionFieldSpec"][];
            /** Settings Resources */
            settings_resources: components["schemas"]["PluginSettingsResourceSpec"][];
            /** Settings Ui Blocks */
            settings_ui_blocks: components["schemas"]["SettingsUIBlockSpec"][];
            /**
             * Update Available
             * @default false
             */
            update_available: boolean;
            /** Version */
            version: string;
        };
        /** PluginRegistryResponse */
        PluginRegistryResponse: {
            /** Install Fingerprint */
            install_fingerprint: string;
            /** Plugins */
            plugins: components["schemas"]["PluginRegistryEntryResponse"][];
            /**
             * Registry Version
             * @constant
             */
            registry_version: "4";
        };
        /** PluginSettingsActionResponse */
        PluginSettingsActionResponse: {
            /** Action Id */
            action_id: string;
            /**
             * Button Label
             * @default Run
             */
            button_label: string;
            /**
             * Button Label Translated
             * @default null
             */
            button_label_translated: string | null;
            /**
             * Contribution Id
             * @default
             */
            contribution_id: string;
            /** @default null */
            contribution_type: components["schemas"]["ContributionType"] | null;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Description Translated
             * @default null
             */
            description_translated: string | null;
            /**
             * Destructive
             * @default false
             */
            destructive: boolean;
            /** Label */
            label: string;
            /**
             * Label Translated
             * @default null
             */
            label_translated: string | null;
            /**
             * Order
             * @default 0
             */
            order: number;
            /**
             * Persist Settings On Success
             * @default false
             */
            persist_settings_on_success: boolean;
            /**
             * Poll Interval Ms
             * @default 2000
             */
            poll_interval_ms: number;
            /**
             * Presentation
             * @default inline
             * @enum {string}
             */
            presentation: "inline" | "qr_code";
            /**
             * Requires Enabled
             * @default true
             */
            requires_enabled: boolean;
            /**
             * Surface
             * @default extensions
             * @enum {string}
             */
            surface: "extensions" | "tools" | "timeline";
            /**
             * Timeout Ms
             * @default 480000
             */
            timeout_ms: number;
        };
        /** PluginSettingsActionRunResponse */
        PluginSettingsActionRunResponse: {
            /** Action Id */
            action_id: string;
            /** Connection Id */
            connection_id: string;
            /** Data */
            data: {
                [key: string]: unknown;
            };
            /**
             * Message
             * @default
             */
            message: string;
            /** Plugin Id */
            plugin_id: string;
            /** Session Id */
            session_id: string;
            /** Settings Updates */
            settings_updates: {
                [key: string]: unknown;
            };
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "succeeded" | "failed" | "cancelled" | "uncertain";
        };
        /**
         * PluginSettingsActionSpec
         * @description Host-rendered settings action declared by a plugin.
         *
         *     The host owns routing and UI chrome, while the plugin owns the action
         *     implementation and any provider-specific protocol details.
         */
        PluginSettingsActionSpec: {
            /** Action Id */
            action_id: string;
            /**
             * Button Label
             * @default Run
             */
            button_label: string;
            /**
             * Contribution Id
             * @default
             */
            contribution_id: string;
            /** @default null */
            contribution_type: components["schemas"]["ContributionType"] | null;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Destructive
             * @default false
             */
            destructive: boolean;
            /** Label */
            label: string;
            /**
             * Order
             * @default 0
             */
            order: number;
            /**
             * Persist Settings On Success
             * @default false
             */
            persist_settings_on_success: boolean;
            /**
             * Poll Interval Ms
             * @default 2000
             */
            poll_interval_ms: number;
            /**
             * Presentation
             * @default inline
             * @enum {string}
             */
            presentation: "inline" | "qr_code";
            /**
             * Requires Enabled
             * @default true
             */
            requires_enabled: boolean;
            /**
             * Surface
             * @default extensions
             * @enum {string}
             */
            surface: "extensions" | "tools" | "timeline";
            /**
             * Timeout Ms
             * @default 480000
             */
            timeout_ms: number;
        };
        /** PluginSettingsResourceResponse */
        PluginSettingsResourceResponse: {
            /** Connection Id */
            connection_id: string;
            /**
             * Data
             * @default null
             */
            data: unknown;
            /** Plugin Id */
            plugin_id: string;
            /** Resource Name */
            resource_name: string;
            /** Resource Type */
            resource_type: string;
        };
        /**
         * PluginSettingsResourceSpec
         * @description Read-only settings resource exposed by a plugin.
         */
        PluginSettingsResourceSpec: {
            /**
             * Description
             * @default
             */
            description: string;
            /** Metadata */
            metadata: {
                [key: string]: unknown;
            };
            /**
             * Requires Enabled
             * @default true
             */
            requires_enabled: boolean;
            /** Resource Name */
            resource_name: string;
            /**
             * Resource Type
             * @default collection
             * @enum {string}
             */
            resource_type: "collection" | "channel_status";
        };
        /** PluginSettingsUiBlockResponse */
        PluginSettingsUiBlockResponse: {
            /** Block Id */
            block_id: string;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Description Translated
             * @default null
             */
            description_translated: string | null;
            /**
             * Presentation
             * @default list
             * @enum {string}
             */
            presentation: "calendar_list" | "list" | "permission_status";
            /** Resource Name */
            resource_name: string;
            /** Title */
            title: string;
            /**
             * Title Translated
             * @default null
             */
            title_translated: string | null;
            /**
             * Type
             * @default resource_picker
             * @constant
             */
            type: "resource_picker";
            /** Value Key */
            value_key: string;
        };
        /** PluginsListResponse */
        PluginsListResponse: {
            /** Plugins */
            plugins: components["schemas"]["PluginPackageResponse"][];
            /** Total */
            total: number;
        };
        /**
         * SettingsUIBlockSpec
         * @description Host-rendered custom settings block declared by a plugin.
         *
         *     Blocks are read-only or selection widgets whose underlying data comes from a
         *     ``PluginSettingsResourceSpec``. The ``presentation`` hint tells the host
         *     which widget to render. New presentations may be added over time as the
         *     plugin platform matures.
         *
         *     ``value_key`` is only meaningful for blocks that bind a selection back to a
         *     settings field (e.g. ``calendar_list``). Read-only presentations like
         *     ``permission_status`` ignore it; plugins should still pass a stable value
         *     such as ``"_readonly"`` to keep the schema stable.
         */
        SettingsUIBlockSpec: {
            /** Block Id */
            block_id: string;
            /**
             * Depends On Key
             * @default null
             */
            depends_on_key: string | null;
            /** Depends On Values */
            depends_on_values: string[];
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Presentation
             * @default list
             * @enum {string}
             */
            presentation: "calendar_list" | "list" | "permission_status";
            /** Resource Name */
            resource_name: string;
            /** Title */
            title: string;
            /**
             * Type
             * @default resource_picker
             * @constant
             */
            type: "resource_picker";
            /** Value Key */
            value_key: string;
        };
        /**
         * SuggestionDescriptor
         * @description Declares how this plugin should be surfaced to users who lack it.
         *
         *     See docs/plugin-suggestion-descriptor.md for the author guide.
         */
        SuggestionDescriptor: {
            /** Category */
            category: string;
            /**
             * Data Locality
             * @default local_only
             * @enum {string}
             */
            data_locality: "local_only" | "uploads";
            /**
             * Icon
             * @default null
             */
            icon: string | null;
            /** Local Requirements */
            local_requirements: (components["schemas"]["LocalRequirementFileExists"] | components["schemas"]["LocalRequirementExecutableInPath"] | components["schemas"]["LocalRequirementAppInstalled"])[];
            /** Platform Support */
            platform_support: string[];
            rationale: components["schemas"]["LocalizedText"];
            /**
             * Setup Time Estimate Seconds
             * @default 30
             */
            setup_time_estimate_seconds: number;
            surfaces: components["schemas"]["SuggestionSurfacesSpec"];
            triggers: components["schemas"]["Triggers"];
        };
        /**
         * SuggestionSurfaceSpec
         * @description Plugin-owned presentation for one recommendation surface.
         */
        SuggestionSurfaceSpec: {
            /**
             * Order
             * @default 100
             */
            order: number;
            /** @default null */
            rationale: components["schemas"]["LocalizedText"] | null;
            /** @default null */
            scope: components["schemas"]["LocalizedText"] | null;
        };
        /**
         * SuggestionSurfacesSpec
         * @description Recommendation surfaces where the plugin opts in to appear.
         */
        SuggestionSurfacesSpec: {
            /** @default null */
            empty_state: components["schemas"]["SuggestionSurfaceSpec"] | null;
            /** @default null */
            first_context: components["schemas"]["SuggestionSurfaceSpec"] | null;
        };
        /**
         * Triggers
         * @description Conditions under which a plugin should be auto-suggested.
         *
         *     All three categories are OR-combined: any matching intent, entity, or keyword
         *     contributes to the match score (weighted by signal type in the matcher).
         */
        Triggers: {
            /** Entities */
            entities: string[];
            /** Intents */
            intents: string[];
            /** Keywords */
            keywords: {
                [key: string]: string[];
            };
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
