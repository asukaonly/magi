// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ASRJob */
        ASRJob: {
            /**
             * Error
             * @default null
             */
            error: string | null;
            /** Expires At */
            expires_at: number;
            /** Request Id */
            request_id: string;
            /** @default null */
            result: components["schemas"]["TranscriptResult"] | null;
            /** Runtime Id */
            runtime_id: string;
            /**
             * State
             * @enum {string}
             */
            state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
        };
        /** ASRModel */
        ASRModel: {
            /**
             * Error
             * @default null
             */
            error: string | null;
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** License */
            license: string;
            /** License Url */
            license_url: string;
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /**
             * Recommended
             * @default false
             */
            recommended: boolean;
            /** Size Bytes */
            size_bytes: number;
            /** Source Url */
            source_url: string;
            /**
             * State
             * @enum {string}
             */
            state: "missing" | "downloading" | "ready" | "failed" | "cancelled";
        };
        /** ASRModels */
        ASRModels: {
            /** Models */
            models: components["schemas"]["ASRModel"][];
        };
        /** ASRStatus */
        ASRStatus: {
            /** Config Revision */
            config_revision: string;
            /** Enabled */
            enabled: boolean;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Mode
             * @enum {string}
             */
            mode: "local" | "remote";
            /**
             * Model
             * @default null
             */
            model: string | null;
            /**
             * Provider Name
             * @default null
             */
            provider_name: string | null;
            /** Ready */
            ready: boolean;
            /** Runtime Id */
            runtime_id: string;
        };
        /** TranscriptResult */
        TranscriptResult: {
            /**
             * Engine
             * @enum {string}
             */
            engine: "local" | "remote";
            /**
             * Language
             * @default null
             */
            language: string | null;
            /** Model */
            model: string;
            /** No Speech */
            no_speech: boolean;
            /** Text */
            text: string;
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
