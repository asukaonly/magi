// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ChatDisplayMessage
         * @description Typed read model for chat history and display timeline messages.
         */
        ChatDisplayMessage: {
            /**
             * Allow Trace Collapse
             * @default false
             */
            allow_trace_collapse?: boolean;
            /**
             * Attachments
             * @default null
             */
            attachments?: {
                [key: string]: unknown;
            }[] | null;
            /** Content */
            content: string;
            /** Kind */
            kind: string;
            /**
             * Label
             * @default null
             */
            label?: {
                [key: string]: unknown;
            } | null;
            /**
             * Message Id
             * @default null
             */
            message_id?: string | null;
            /**
             * Message Kind
             * @default null
             */
            message_kind?: string | null;
            /**
             * Payload
             * @default null
             */
            payload?: {
                [key: string]: unknown;
            } | null;
            /**
             * Persona Id
             * @default null
             */
            persona_id?: string | null;
            /**
             * Reply To
             * @default null
             */
            reply_to?: {
                [key: string]: unknown;
            } | null;
            /** Role */
            role: string;
            /**
             * Run State
             * @default null
             */
            run_state?: {
                [key: string]: unknown;
            } | null;
            /** Timestamp */
            timestamp: number;
            /**
             * Trace Available
             * @default false
             */
            trace_available?: boolean;
            /**
             * Trace Display Mode
             * @default null
             */
            trace_display_mode?: string | null;
            /**
             * Trace Summary
             * @default null
             */
            trace_summary?: {
                [key: string]: unknown;
            } | null;
            /**
             * Turn Id
             * @default null
             */
            turn_id?: string | null;
        };
        /**
         * ChatSessionSummary
         * @description Typed session summary returned by the chat read model.
         */
        ChatSessionSummary: {
            /**
             * History Version
             * @default 0
             */
            history_version?: number;
            /** Last Message Preview */
            last_message_preview: string;
            /** Last Timestamp */
            last_timestamp: number;
            /** Last User Message Preview */
            last_user_message_preview: string;
            /** Message Count */
            message_count: number;
            /** Session Id */
            session_id: string;
            /** Title */
            title: string;
            /** Title Overridden */
            title_overridden: boolean;
            /**
             * Workspace Path
             * @default null
             */
            workspace_path?: string | null;
        };
        /** ContextUsageEvent */
        ContextUsageEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductContextUsage"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "context_usage";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** InteractionEvent */
        InteractionEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductInteractionPointer"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "control.ask.answered" | "control.ask.requested" | "control.background.resumed" | "control.background.suspended" | "control.permission.requested" | "control.permission.resolved" | "control.plan.updated";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        JsonValue: unknown;
        /** MessageHiddenEvent */
        MessageHiddenEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductMessageHidden"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "chat_message_hidden";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** MessageUpsertEvent */
        MessageUpsertEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductMessageUpsert"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "chat_message_upserted";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** NotificationEvent */
        NotificationEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductNotificationCount"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "user_notification_added";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** ProductContextUsage */
        ProductContextUsage: {
            /** Input Capacity */
            input_capacity: number;
            /**
             * Measurement
             * @default null
             */
            measurement?: string | null;
            /**
             * Model Id
             * @default null
             */
            model_id?: string | null;
            /**
             * Model Provider
             * @default null
             */
            model_provider?: string | null;
            /** Session Id */
            session_id: string;
            /** Threshold */
            threshold: number;
            /** Timestamp */
            timestamp: number;
            /** Turn Id */
            turn_id: string;
            /**
             * Updated At Ms
             * @default null
             */
            updated_at_ms?: number | null;
            /** Used Tokens */
            used_tokens: number;
            /** User Id */
            user_id: string;
            /** Window Size */
            window_size: number;
        };
        /** ProductEvent */
        ProductEvent: components["schemas"]["MessageUpsertEvent"] | components["schemas"]["MessageHiddenEvent"] | components["schemas"]["TurnControlEvent"] | components["schemas"]["TurnPresentationEvent"] | components["schemas"]["ResponsePreviewEvent"] | components["schemas"]["ResponseDisplayEvent"] | components["schemas"]["ContextUsageEvent"] | components["schemas"]["InteractionEvent"] | components["schemas"]["ResourceChangeEvent"] | components["schemas"]["ResyncEvent"] | components["schemas"]["NotificationEvent"];
        /** ProductInteractionPointer */
        ProductInteractionPointer: {
            /**
             * Request Id
             * @default null
             */
            request_id?: string | null;
            /**
             * Run Id
             * @default null
             */
            run_id?: string | null;
            /** Session Id */
            session_id: string;
            /**
             * User Id
             * @default null
             */
            user_id?: string | null;
        };
        /** ProductMessageHidden */
        ProductMessageHidden: {
            /** Message Id */
            message_id: string;
            /** Session Id */
            session_id: string;
            /** @default null */
            session_summary?: components["schemas"]["ChatSessionSummary"] | null;
            /** User Id */
            user_id: string;
        };
        /** ProductMessageUpsert */
        ProductMessageUpsert: {
            message: components["schemas"]["ChatDisplayMessage"];
            /** Message Id */
            message_id: string;
            /** Session Id */
            session_id: string;
            /** @default null */
            session_summary?: components["schemas"]["ChatSessionSummary"] | null;
            /** User Id */
            user_id: string;
        };
        /** ProductNotificationCount */
        ProductNotificationCount: {
            /** Unread Count */
            unread_count: number;
        };
        /** ProductResourceChange */
        ProductResourceChange: {
            /** Resource */
            resource: string;
        };
        /** ProductResponseDisplay */
        ProductResponseDisplay: {
            /** Attachments */
            attachments?: {
                [key: string]: components["schemas"]["JsonValue"];
            }[];
            /** Content */
            content: string;
            /** Is Final */
            is_final: boolean;
            /**
             * Message Id
             * @default null
             */
            message_id?: string | null;
            /**
             * Message Kind
             * @default null
             */
            message_kind?: string | null;
            /**
             * Message Payload
             * @default null
             */
            message_payload?: {
                [key: string]: components["schemas"]["JsonValue"];
            } | null;
            /**
             * Persona Id
             * @default null
             */
            persona_id?: string | null;
            /**
             * Reply To Message Id
             * @default null
             */
            reply_to_message_id?: string | null;
            /** Session Id */
            session_id: string;
            /** Timestamp */
            timestamp: number;
            /**
             * Trace Available
             * @default false
             */
            trace_available?: boolean;
            /**
             * Turn Id
             * @default null
             */
            turn_id?: string | null;
            /** User Id */
            user_id: string;
            /**
             * Ux Plan
             * @default null
             */
            ux_plan?: {
                [key: string]: components["schemas"]["JsonValue"];
            } | null;
        };
        /** ProductResponsePreview */
        ProductResponsePreview: {
            event: components["schemas"]["ProductTextPreview"];
            /** Is Final */
            is_final: boolean;
            /**
             * Persona Id
             * @default null
             */
            persona_id?: string | null;
            /** Seq */
            seq: number;
            /** Session Id */
            session_id: string;
            /** Timestamp */
            timestamp: number;
            /** Turn Id */
            turn_id: string;
            /** User Id */
            user_id: string;
        };
        /** ProductResyncRequired */
        ProductResyncRequired: {
            /** Reason */
            reason: string;
        };
        /** ProductTextPreview */
        ProductTextPreview: {
            /**
             * Error Kind
             * @default null
             */
            error_kind?: string | null;
            /**
             * Error Message
             * @default null
             */
            error_message?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "text_delta" | "text_flush" | "text_reset" | "status_update" | "error" | "done";
            /**
             * Step Label
             * @default null
             */
            step_label?: string | null;
            /**
             * Text
             * @default null
             */
            text?: string | null;
        };
        /** ProductTurnControl */
        ProductTurnControl: {
            /** Can Cancel */
            can_cancel: boolean;
            /**
             * Label
             * @default null
             */
            label?: string | null;
            /**
             * Run Id
             * @default null
             */
            run_id?: string | null;
            /** Session Id */
            session_id: string;
            /** State */
            state: string;
            /** Timestamp */
            timestamp: number;
            /** Turn Id */
            turn_id: string;
            /** User Id */
            user_id: string;
        };
        /** ProductTurnPresentation */
        ProductTurnPresentation: {
            /**
             * Message Id
             * @default null
             */
            message_id?: string | null;
            /**
             * Message Kind
             * @default null
             */
            message_kind?: string | null;
            /** Session Id */
            session_id: string;
            /** Timestamp */
            timestamp: number;
            /** Turn Id */
            turn_id: string;
            /** User Id */
            user_id: string;
            /** Ux Plan */
            ux_plan: {
                [key: string]: components["schemas"]["JsonValue"];
            };
        };
        /** ResourceChangeEvent */
        ResourceChangeEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductResourceChange"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "state.changed";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** ResponseDisplayEvent */
        ResponseDisplayEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductResponseDisplay"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "agent_response";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** ResponsePreviewEvent */
        ResponsePreviewEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductResponsePreview"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "agent_response_chunk";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** ResyncEvent */
        ResyncEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductResyncRequired"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "resync_required";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** TurnControlEvent */
        TurnControlEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductTurnControl"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "turn_execution_control";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** TurnPresentationEvent */
        TurnPresentationEvent: {
            /**
             * Contract Version
             * @constant
             */
            contract_version: 1;
            data: components["schemas"]["ProductTurnPresentation"];
            /**
             * Epoch
             * Format: uuid
             */
            epoch: string;
            /** Event Id */
            event_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            event_type: "turn_ux_plan";
            /** Sequence */
            sequence: number;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
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
