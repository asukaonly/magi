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
        /** ModelDownloadStatus */
        ModelDownloadStatus: {
            /** @default null */
            download: components["schemas"]["DownloadProgress"] | null;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /** Model Id */
            model_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "downloading" | "completed" | "failed" | "cancelled" | "not_found";
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
