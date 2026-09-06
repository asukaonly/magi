// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ClearHistoryResponse
         * @description Confirmed immutable transcript snapshot removed by a history clear.
         */
        ClearHistoryResponse: {
            /**
             * Cleanup Pending
             * @default false
             */
            cleanup_pending: boolean;
            /** Cleared Message Ids */
            cleared_message_ids: string[];
            /** Cleared Turn Ids */
            cleared_turn_ids: string[];
            /** Message */
            message: string;
            /** Session Id */
            session_id: string;
            /** Success */
            success: boolean;
            /** User Id */
            user_id: string;
        };
        /**
         * ClearMemoryResponseModel
         * @description Confirmed full-memory clear with any deferred recovery warnings.
         */
        ClearMemoryResponseModel: {
            results: components["schemas"]["ClearResultsModel"];
            /** Success */
            success: boolean;
            /** Warnings */
            warnings: string[];
        };
        /**
         * ClearResultModel
         * @description Count returned for one cleared product area.
         */
        ClearResultModel: {
            /** Cleared */
            cleared: boolean;
            /** Count */
            count: number;
        };
        /**
         * ClearResultsModel
         * @description Every memory and conversation area covered by a full clear.
         */
        ClearResultsModel: {
            chat_context: components["schemas"]["ClearResultModel"];
            l0: components["schemas"]["ClearResultModel"];
            l1: components["schemas"]["ClearResultModel"];
            l2: components["schemas"]["ClearResultModel"];
            l3: components["schemas"]["ClearResultModel"];
            l4: components["schemas"]["ClearResultModel"];
        };
        /**
         * DeleteL1EventResponse
         * @description Confirmed source-event deletion and its product scope.
         */
        DeleteL1EventResponse: {
            /** Deleted */
            deleted: boolean;
            /**
             * Deletion Scope
             * @enum {string}
             */
            deletion_scope: "projected_memory_only" | "source_event";
            /** Event Id */
            event_id: string;
        };
        /**
         * DeleteMessageResponse
         * @description Confirmed message removal and its remaining cleanup state.
         */
        DeleteMessageResponse: {
            /**
             * Cleanup Pending
             * @default false
             */
            cleanup_pending: boolean;
            /** Deleted Message Id */
            deleted_message_id: string;
            /** Session Id */
            session_id: string;
            /** Success */
            success: boolean;
            /** User Id */
            user_id: string;
        };
        /**
         * DeleteSessionResponse
         * @description Confirmed session removal and its remaining cleanup state.
         */
        DeleteSessionResponse: {
            /**
             * Cleanup Pending
             * @default false
             */
            cleanup_pending: boolean;
            /** Deleted Session Id */
            deleted_session_id: string;
            /** Success */
            success: boolean;
            /** User Id */
            user_id: string;
        };
        /**
         * ForgetEntityResponse
         * @description Confirmed cascade deletion counts for an entity or time range.
         */
        ForgetEntityResponse: {
            /** L1 Events Deleted */
            l1_events_deleted: number;
            /** L2 Counts */
            l2_counts: {
                [key: string]: number;
            };
        };
        /**
         * ForgetEpisodeResponse
         * @description Confirmed episode deletion and the affected source events.
         */
        ForgetEpisodeResponse: {
            /** Episode Id */
            episode_id: string;
            /** Event Ids */
            event_ids: string[];
            /** L1 Events Deleted */
            l1_events_deleted: number;
        };
        /** HistoryImportAppendResponse */
        HistoryImportAppendResponse: {
            /** Added Source Count */
            added_source_count: number;
            /** Duplicate Source Count */
            duplicate_source_count: number;
            job: components["schemas"]["HistoryImportJobResponse"];
        };
        /** HistoryImportJobResponse */
        HistoryImportJobResponse: {
            /** Connection Id */
            connection_id: string | null;
            /** Created At */
            created_at: number;
            /**
             * Detected Kind
             * @enum {string}
             */
            detected_kind: "document" | "chat" | "mixed";
            /** Error Code */
            error_code: string | null;
            /** Imported Count */
            imported_count: number;
            /** Importer Id */
            importer_id: string | null;
            /** Importer Plugin Id */
            importer_plugin_id: string | null;
            /** Included Source Ids */
            included_source_ids: string[];
            /** Job Id */
            job_id: string;
            /** Meaningful Records */
            meaningful_records: number;
            /** Participants */
            participants: components["schemas"]["HistoryImportParticipantResponse"][];
            /** Preview Records */
            preview_records: components["schemas"]["HistoryImportRecordPreviewResponse"][];
            /** Projected Count */
            projected_count: number;
            /** Quick Imported Count */
            quick_imported_count: number;
            /** Quick Max Records */
            quick_max_records: number;
            /** Quick Ready */
            quick_ready: boolean;
            /** Quick Target Records */
            quick_target_records: number;
            /** Self Participant Ids */
            self_participant_ids: string[];
            /** Source Ids */
            source_ids: string[];
            /** Source Type */
            source_type: string;
            /** Sources */
            sources: components["schemas"]["HistoryImportSourceSummaryResponse"][];
            /**
             * Status
             * @enum {string}
             */
            status: "preview_ready" | "running" | "ready" | "completed" | "failed" | "deleted";
            /** Total Records */
            total_records: number;
            /** Updated At */
            updated_at: number;
            warning_summary: components["schemas"]["HistoryImportWarningSummaryResponse"];
        };
        /** HistoryImportParticipantResponse */
        HistoryImportParticipantResponse: {
            /** Display Name */
            display_name: string;
            /** Is Document Author */
            is_document_author: boolean;
            /** Meaningful Count */
            meaningful_count: number;
            /** Message Count */
            message_count: number;
            /** Participant Id */
            participant_id: string;
            /** Sample */
            sample: string;
        };
        /** HistoryImportRecordPreviewResponse */
        HistoryImportRecordPreviewResponse: {
            /** Content */
            content: string;
            /** Event At */
            event_at: number;
            /** Is Document Author */
            is_document_author: boolean;
            /** Session Id */
            session_id: string;
            /** Session Seq */
            session_seq: number;
            /** Source Id */
            source_id: string;
            /** Source Name */
            source_name: string;
            /** Speaker Id */
            speaker_id: string;
            /** Speaker Name */
            speaker_name: string;
            /** Timestamp Confidence */
            timestamp_confidence: string;
        };
        /** HistoryImportSourcePreviewResponse */
        HistoryImportSourcePreviewResponse: {
            /**
             * Detected Kind
             * @enum {string}
             */
            detected_kind: "document" | "chat" | "mixed";
            /** Records */
            records: components["schemas"]["HistoryImportRecordPreviewResponse"][];
            /** Source Id */
            source_id: string;
            /** Source Name */
            source_name: string;
            /** Truncated */
            truncated: boolean;
        };
        /** HistoryImportSourceSummaryResponse */
        HistoryImportSourceSummaryResponse: {
            /**
             * Detected Kind
             * @enum {string}
             */
            detected_kind: "document" | "chat" | "mixed";
            /** First Event At */
            first_event_at: number;
            /** Included */
            included: boolean;
            /** Last Event At */
            last_event_at: number;
            /** Meaningful Count */
            meaningful_count: number;
            /** Record Count */
            record_count: number;
            /** Sample */
            sample: string;
            /** Source Id */
            source_id: string;
            /** Source Name */
            source_name: string;
            /** Timestamp Confidence */
            timestamp_confidence: string;
        };
        /** HistoryImportWarningSummaryResponse */
        HistoryImportWarningSummaryResponse: {
            /** Codes */
            codes: string[];
            /** Total Count */
            total_count: number;
            /** Truncated */
            truncated: boolean;
        };
        /** HistoryImporterResponse */
        HistoryImporterResponse: {
            /** Accepted Extensions */
            accepted_extensions: string[];
            /** Connection Display Name */
            connection_display_name: string | null;
            /** Connection Id */
            connection_id: string;
            /** Description */
            description: string;
            /** Description I18N */
            description_i18n: {
                [key: string]: string;
            };
            /** Display Name */
            display_name: string;
            /** Display Name I18N */
            display_name_i18n: {
                [key: string]: string;
            };
            /** Export Help Url */
            export_help_url: string | null;
            /** Importer Id */
            importer_id: string;
            /**
             * Participant Identity Scope
             * @enum {string}
             */
            participant_identity_scope: "source" | "export";
            /** Plugin Id */
            plugin_id: string;
        };
        /**
         * MemoryPortabilityOperation
         * @description User-facing snapshot of one memory portability job.
         */
        MemoryPortabilityOperation: {
            /**
             * Completed At
             * @default null
             */
            completed_at: string | null;
            /** Created At */
            created_at: string;
            /**
             * Error Code
             * @default null
             */
            error_code: string | null;
            /**
             * Error Message
             * @default null
             */
            error_message: string | null;
            /**
             * File Size Bytes
             * @default null
             */
            file_size_bytes: number | null;
            /**
             * Index Rebuild Status
             * @default null
             */
            index_rebuild_status: string | null;
            /**
             * Inspection
             * @default null
             */
            inspection: (components["schemas"]["PasswordRequiredMemoryRestoreInspection"] | components["schemas"]["ReadyMemoryRestoreInspection"]) | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "backup" | "export" | "inspect" | "restore";
            /** Operation Id */
            operation_id: string;
            /**
             * Output Path
             * @default null
             */
            output_path: string | null;
            /**
             * Phase
             * @default queued
             */
            phase: string;
            /**
             * Progress Percent
             * @default 0
             */
            progress_percent: number;
            /** Record Counts */
            record_counts: {
                [key: string]: number;
            };
            /**
             * Rollback Performed
             * @default false
             */
            rollback_performed: boolean;
            /**
             * Safety Backup Path
             * @default null
             */
            safety_backup_path: string | null;
            /**
             * Status
             * @default pending
             * @enum {string}
             */
            status: "pending" | "running" | "succeeded" | "failed";
        };
        /**
         * PasswordRequiredMemoryRestoreInspection
         * @description Secret-free result for an encrypted package awaiting a password.
         */
        PasswordRequiredMemoryRestoreInspection: {
            /**
             * Encrypted
             * @constant
             */
            encrypted: true;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            state: "password_required";
        };
        /**
         * ReadyMemoryRestoreInspection
         * @description Validated metadata for one private restore candidate.
         */
        ReadyMemoryRestoreInspection: {
            /** Candidate Id */
            candidate_id: string;
            /**
             * Compatibility
             * @enum {string}
             */
            compatibility: "compatible" | "upgrade_required" | "unsupported";
            /** Created At */
            created_at: string;
            /** Encrypted */
            encrypted: boolean;
            /** Expires At */
            expires_at: string;
            /** Format Version */
            format_version: number;
            /** Magi Version */
            magi_version: string;
            /** Record Counts */
            record_counts: {
                [key: string]: number;
            };
            /** Scope */
            scope: string[];
            /** Source Fingerprint */
            source_fingerprint: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            state: "ready";
            /** Warnings */
            warnings: string[];
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
