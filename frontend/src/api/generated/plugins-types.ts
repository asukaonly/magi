// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
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
         * PluginCapability
         * @description A single self-declared capability shown to the user for install-time
         *     consent. NOT enforced at runtime (no sandbox this iteration).
         *
         *     ``capability`` is a permissive ``str`` for forward-compat: a newer
         *     registry may declare a capability an older app doesn't know, and that must
         *     not break parsing. The authoritative known set is enforced at build time in
         *     magi-plugins ``scripts/build-registry.py`` and rendered with a known map +
         *     graceful fallback in the frontend. Known values: screen_recording,
         *     accessibility, calendar, photos, contacts, system_media, filesystem_read,
         *     filesystem_write, network, subprocess.
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
        /** PluginManifestResponse */
        PluginManifestResponse: {
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
             * Icon
             * @default
             */
            icon: string;
            /** Manifest Path */
            manifest_path: string;
            /** Name */
            name: string;
            /** Official */
            official: boolean;
            /** Plugin Dir */
            plugin_dir: string;
            /** Plugin Id */
            plugin_id: string;
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
            /** Trusted */
            trusted: boolean;
        };
        /** PluginRegistryEntryResponse */
        PluginRegistryEntryResponse: {
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
            /**
             * Min Sdk Version
             * @default
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
             * Path
             * @default
             */
            path: string;
            /** Platforms */
            platforms: string[];
            /** Plugin Id */
            plugin_id: string;
            /**
             * Repository
             * @default
             */
            repository: string;
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
        /** PluginSettingsActionRunResponse */
        PluginSettingsActionRunResponse: {
            /** Action Id */
            action_id: string;
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
            status: "pending" | "succeeded" | "failed" | "cancelled";
        };
        /** PluginSettingsResourceResponse */
        PluginSettingsResourceResponse: {
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
        /** PluginsListResponse */
        PluginsListResponse: {
            /** Plugins */
            plugins: components["schemas"]["PluginPackageResponse"][];
            /** Total */
            total: number;
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
