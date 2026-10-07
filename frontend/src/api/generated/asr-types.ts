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
            /** @default null */
            download: components["schemas"]["DownloadProgress"] | null;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Family
             * @enum {string}
             */
            family: "paraformer" | "sense_voice" | "qwen3_asr" | "whisper";
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** License */
            license: string;
            /** License Url */
            license_url: string;
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
        /** DownloadProgress */
        DownloadProgress: {
            /**
             * Downloaded Bytes
             * @default 0
             */
            downloaded_bytes: number;
            /**
             * Eta Seconds
             * @default null
             */
            eta_seconds: number | null;
            /**
             * Files Completed
             * @default 0
             */
            files_completed: number;
            /**
             * Phase
             * @default connecting
             * @enum {string}
             */
            phase: "connecting" | "downloading" | "retrying" | "verifying" | "completed" | "cancelled" | "failed";
            /**
             * Speed Bps
             * @default 0
             */
            speed_bps: number;
            /**
             * Total Bytes
             * @default null
             */
            total_bytes: number | null;
            /**
             * Total Files
             * @default 0
             */
            total_files: number;
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
