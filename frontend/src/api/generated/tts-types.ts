// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** MessageSource */
        MessageSource: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "message";
            /** Message Id */
            message_id: string;
            /** Revision */
            revision: string;
            /** Session Id */
            session_id: string;
        };
        /** SynthesisJob */
        SynthesisJob: {
            /**
             * Cleaner Version
             * @default 1
             */
            cleaner_version: string;
            /** Content Hash */
            content_hash: string;
            /** Engine */
            engine: string;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /** Expires At */
            expires_at: number;
            /** Job Id */
            job_id: string;
            /** Model */
            model: string;
            /**
             * Ready Segments
             * @default 0
             */
            ready_segments: number;
            /** Request Id */
            request_id: string;
            /** Speed */
            speed: number;
            /**
             * State
             * @enum {string}
             */
            state: "ready" | "running" | "completed" | "cancelling" | "cancelled" | "failed" | "unknown";
            /** Total Segments */
            total_segments: number;
            /** Voice */
            voice: string;
        };
        /** SynthesisRequest */
        SynthesisRequest: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /** Source */
            source: components["schemas"]["TextSource"] | components["schemas"]["MessageSource"];
        };
        /** TTSConfiguration */
        TTSConfiguration: {
            /** Local Voices */
            local_voices: components["schemas"]["VoiceInfo"][];
            model: components["schemas"]["TTSModelStatus"];
            /** Revision */
            revision: string;
            settings: components["schemas"]["TTSSettings"];
            /** Voices */
            voices: components["schemas"]["VoiceInfo"][];
        };
        /** TTSConfigurationUpdate */
        TTSConfigurationUpdate: {
            /** Revision */
            revision: string;
            settings: components["schemas"]["TTSSettings"];
        };
        /** TTSModelStatus */
        TTSModelStatus: {
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Model Id
             * @default kokoro-multi-lang-v1_0
             */
            model_id: string;
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
            /**
             * Runtime Available
             * @default false
             */
            runtime_available: boolean;
            /**
             * State
             * @default missing
             * @enum {string}
             */
            state: "missing" | "downloading" | "ready" | "failed" | "cancelled";
        };
        /** TTSSettings */
        TTSSettings: {
            /**
             * Engine
             * @default local
             * @enum {string}
             */
            engine: "local" | "remote";
            /**
             * Local Model
             * @default kokoro-multi-lang-v1_0
             * @constant
             */
            local_model: "kokoro-multi-lang-v1_0";
            /**
             * Local Speed
             * @default 1
             */
            local_speed: number;
            /**
             * Local Voice
             * @default zf_xiaobei
             */
            local_voice: string;
            /**
             * Provider Id
             * @default null
             */
            provider_id: string | null;
        };
        /** TextSource */
        TextSource: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "text";
            /** Text */
            text: string;
        };
        /** VoiceInfo */
        VoiceInfo: {
            /** Id */
            id: string;
            /** Language */
            language: string;
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
