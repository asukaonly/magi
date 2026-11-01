// Generated from production response schemas. Run npm run contracts:generate.
export interface paths {
    "/api/messages/confirmation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Confirm Send
         * @description Read a receipt; this operation never dispatches or retries user work.
         */
        post: operations["confirm_send_confirmation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/messages/session/{session_id}/turn/{turn_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Turn Snapshot */
        get: operations["get_turn_snapshot_session__session_id__turn__turn_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnswerConfirmationRequest */
        AnswerConfirmationRequest: {
            /** Answer */
            answer: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "ask_response";
            /** Request Id */
            request_id: string;
            /** Session Id */
            session_id: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** SendConfirmation */
        SendConfirmation: {
            /** Identity */
            identity: string;
            /** Safe To Retry */
            safe_to_retry: boolean;
            /** Session Id */
            session_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "confirmed" | "absent" | "concluded";
        };
        /** SendConfirmationRequest */
        SendConfirmationRequest: components["schemas"]["TurnConfirmationRequest"] | components["schemas"]["AnswerConfirmationRequest"];
        /** TurnConfirmationRequest */
        TurnConfirmationRequest: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "turn";
            /** Session Id */
            session_id: string;
            /** Turn Id */
            turn_id: string;
        };
        /** TurnSnapshot */
        TurnSnapshot: {
            /**
             * Acceptance
             * @enum {string}
             */
            acceptance: "accepted" | "absent" | "retired";
            /** Can Resubmit */
            can_resubmit: boolean;
            /** Presentation Ends At Ms */
            presentation_ends_at_ms: number | null;
            /** Response Complete */
            response_complete: boolean;
            /** Revision */
            revision: string;
            /** Session Id */
            session_id: string;
            /** State */
            state: ("queued" | "running" | "cancelling" | "detaching" | "completed" | "failed" | "cancelled" | "blocked" | "interrupted" | "merged" | "discarded" | "superseded") | null;
            /** Terminal */
            terminal: boolean;
            /** Turn Id */
            turn_id: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    confirm_send_confirmation_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SendConfirmationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SendConfirmation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_turn_snapshot_session__session_id__turn__turn_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
                turn_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TurnSnapshot"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
