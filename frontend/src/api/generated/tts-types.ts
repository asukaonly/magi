// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
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
            /** @default null */
            preview_settings: components["schemas"]["TTSSettings"] | null;
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
            /** Models */
            models: components["schemas"]["TTSModelChoice"][];
            /** Reference Audio */
            reference_audio: components["schemas"]["TTSReferenceAudio"][];
            /** Revision */
            revision: string;
            settings: components["schemas"]["TTSSettings"];
        };
        /** TTSConfigurationUpdate */
        TTSConfigurationUpdate: {
            /** Revision */
            revision: string;
            settings: components["schemas"]["TTSSettings"];
        };
        /** TTSDirectoryRequest */
        TTSDirectoryRequest: {
            /**
             * Codec Path
             * @default
             */
            codec_path: string;
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "voxcpm2-8bit" | "moss-tts-nano" | "qwen3-tts-customvoice-8bit" | "moss-tts-local-1.5-4bit" | "kokoro-multi-lang-v1_0" | "vits-melo-tts-zh_en";
            /** Path */
            path: string;
        };
        /** TTSModelChoice */
        TTSModelChoice: {
            /**
             * Companion Model
             * @default false
             */
            companion_model: boolean;
            /**
             * Custom Model
             * @default false
             */
            custom_model: boolean;
            /**
             * Custom Voice
             * @default false
             */
            custom_voice: boolean;
            /**
             * Download Bytes
             * @default 0
             */
            download_bytes: number;
            /** Emotions */
            emotions: string[];
            /**
             * Engine
             * @enum {string}
             */
            engine: "local" | "remote";
            /**
             * Experimental
             * @default false
             */
            experimental: boolean;
            /**
             * Instructions
             * @default false
             */
            instructions: boolean;
            /** Model Id */
            model_id: string;
            /** Name */
            name: string;
            /**
             * Provider Id
             * @default null
             */
            provider_id: string | null;
            /**
             * Provider Name
             * @default
             */
            provider_name: string;
            /**
             * Recommended
             * @default false
             */
            recommended: boolean;
            /**
             * Reference Audio
             * @default none
             * @enum {string}
             */
            reference_audio: "none" | "optional" | "required";
            /**
             * Runtime
             * @default onnx
             * @enum {string}
             */
            runtime: "onnx" | "mlx" | "remote";
            /**
             * Seed
             * @default false
             */
            seed: boolean;
            /**
             * Speed Max
             * @default null
             */
            speed_max: number | null;
            /**
             * Speed Min
             * @default null
             */
            speed_min: number | null;
            /** @default null */
            status: components["schemas"]["TTSModelStatus"] | null;
            /**
             * Voice Description
             * @default false
             */
            voice_description: boolean;
            /** Voices */
            voices: components["schemas"]["VoiceInfo"][];
        };
        /** TTSModelStatus */
        TTSModelStatus: {
            /** @default null */
            download: components["schemas"]["DownloadProgress"] | null;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Model Id
             * @default voxcpm2-8bit
             */
            model_id: string;
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
        /** TTSReferenceAudio */
        TTSReferenceAudio: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Seconds */
            seconds: number;
        };
        /** TTSSettings */
        TTSSettings: {
            /**
             * Emotion
             * @default
             */
            emotion: string;
            /**
             * Engine
             * @default local
             * @enum {string}
             */
            engine: "local" | "remote";
            /**
             * Instructions
             * @default
             */
            instructions: string;
            /**
             * Local Codec Path
             * @default
             */
            local_codec_path: string;
            /**
             * Local Model
             * @default voxcpm2-8bit
             * @enum {string}
             */
            local_model: "voxcpm2-8bit" | "moss-tts-nano" | "qwen3-tts-customvoice-8bit" | "moss-tts-local-1.5-4bit" | "kokoro-multi-lang-v1_0" | "vits-melo-tts-zh_en";
            /**
             * Local Model Path
             * @default
             */
            local_model_path: string;
            /**
             * Local Speed
             * @default 1
             */
            local_speed: number;
            /**
             * Local Voice
             * @default
             */
            local_voice: string;
            /**
             * Provider Id
             * @default null
             */
            provider_id: string | null;
            /**
             * Reference Audio
             * @default
             */
            reference_audio: string;
            /**
             * Remote Model
             * @default
             */
            remote_model: string;
            /**
             * Remote Speed
             * @default 1
             */
            remote_speed: number;
            /**
             * Remote Voice
             * @default
             */
            remote_voice: string;
            /**
             * Voice Description
             * @default
             */
            voice_description: string;
            /** Voice Presets */
            voice_presets: components["schemas"]["TTSVoicePreset"][];
            /**
             * Voice Seed
             * @default 42
             */
            voice_seed: number;
        };
        /**
         * TTSVoicePreset
         * @description A named, model-specific voice recipe; never a portable speaker identity.
         */
        TTSVoicePreset: {
            /**
             * Description
             * @default
             */
            description: string;
            /** Id */
            id: string;
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "voxcpm2-8bit" | "moss-tts-nano" | "qwen3-tts-customvoice-8bit" | "moss-tts-local-1.5-4bit" | "kokoro-multi-lang-v1_0" | "vits-melo-tts-zh_en";
            /** Name */
            name: string;
            /**
             * Reference Audio
             * @default
             */
            reference_audio: string;
            /**
             * Seed
             * @default 42
             */
            seed: number;
            /**
             * Speed
             * @default 1
             */
            speed: number;
            /**
             * Voice
             * @default
             */
            voice: string;
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
            /**
             * Name
             * @default
             */
            name: string;
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
