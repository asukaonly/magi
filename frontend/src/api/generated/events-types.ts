// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * BackgroundTask
         * @description Mutable runtime state for one background task.
         *
         *     ``task_id`` is stable across retries; each retry bumps ``attempt_index``
         *     and clears ``started_at`` / ``finished_at`` / ``error`` / ``summary`` /
         *     ``result_payload`` before transitioning back to
         *     ``pending``.
         */
        BackgroundTask: {
            /**
             * Attempt Index
             * @default 0
             */
            attempt_index: number;
            /**
             * Cancel Reason
             * @default null
             */
            cancel_reason: string | null;
            /** Created At */
            created_at: number;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /**
             * Finished At
             * @default null
             */
            finished_at: number | null;
            /** Result Payload */
            result_payload: {
                [key: string]: unknown;
            };
            spec: components["schemas"]["BackgroundTaskSpec"];
            /**
             * Started At
             * @default null
             */
            started_at: number | null;
            /** @default pending */
            status: components["schemas"]["BackgroundTaskStatus"];
            /**
             * Summary
             * @default null
             */
            summary: string | null;
            /** Task Id */
            task_id: string;
            /** Updated At */
            updated_at: number;
            /**
             * User Task Id
             * @default null
             */
            user_task_id: string | null;
        };
        /**
         * BackgroundTaskEvent
         * @description An append-only entry in the task's event log.
         *
         *     Events are recorded for every state transition plus ad-hoc progress
         *     notes. The store guarantees insertion order but does not enforce any
         *     transition validity; the manager is the authority on legal transitions.
         */
        BackgroundTaskEvent: {
            /** Attempt Index */
            attempt_index: number;
            /** Created At */
            created_at: number;
            /** Event Id */
            event_id: string;
            /** Event Type */
            event_type: string;
            from_status: components["schemas"]["BackgroundTaskStatus"] | null;
            /**
             * Message
             * @default
             */
            message: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Task Id */
            task_id: string;
            to_status: components["schemas"]["BackgroundTaskStatus"] | null;
        };
        /**
         * BackgroundTaskSpec
         * @description Immutable input used to (re-)launch a background task.
         *
         *     A spec is created once at dispatch time and is preserved verbatim across
         *     retries; the mutable state lives on :class:`BackgroundTask`.
         */
        BackgroundTaskSpec: {
            /**
             * Agent Run Checkpoint
             * @default null
             */
            agent_run_checkpoint: {
                [key: string]: unknown;
            } | null;
            /**
             * Context Sources
             * @default []
             */
            context_sources: {
                [key: string]: unknown;
            }[];
            /**
             * Ephemeral Context
             * @default null
             */
            ephemeral_context: string | null;
            /**
             * Execution Preset
             * @default background
             */
            execution_preset: string;
            /**
             * Final Response Json Mode
             * @default false
             */
            final_response_json_mode: boolean;
            /** Goal */
            goal: string;
            /**
             * Max Iterations
             * @default 50
             */
            max_iterations: number;
            /** Origin Turn Id */
            origin_turn_id: string;
            /**
             * Parent Run Id
             * @default null
             */
            parent_run_id: string | null;
            /**
             * Pending Message Id
             * @default null
             */
            pending_message_id: string | null;
            /**
             * Priority
             * @default 0
             */
            priority: number;
            /** Reasoning Policy */
            reasoning_policy: {
                [key: string]: unknown;
            };
            /** Run Id */
            run_id: string;
            /** Selected Tools */
            selected_tools: string[];
            /** Session Id */
            session_id: string;
            /**
             * Skill Preapproval Rules
             * @default []
             */
            skill_preapproval_rules: string[];
            /**
             * System Prompt
             * @default
             */
            system_prompt: string;
            /**
             * Task Budget Root Turn Id
             * @default null
             */
            task_budget_root_turn_id: string | null;
            /**
             * Timeout Seconds
             * @default 1800
             */
            timeout_seconds: number | null;
            /** Title */
            title: string;
            /** @default null */
            trigger: components["schemas"]["RunTrigger"] | null;
            /** @default rule */
            trigger_source: components["schemas"]["BackgroundTaskTriggerSource"];
            /** User Id */
            user_id: string;
            /**
             * Working Context
             * @default
             */
            working_context: string;
            /**
             * Workspace Path
             * @default null
             */
            workspace_path: string | null;
        };
        /**
         * BackgroundTaskStatus
         * @description Lifecycle states for a background task.
         *
         *     The valid transitions are:
         *
         *     * ``pending`` → ``running`` (slot acquired) | ``cancelled``
         *     * ``running`` → ``cancelling`` | ``succeeded`` | ``failed``
         *       | ``suspended_waiting_user``
         *     * ``suspended_waiting_user`` → ``running`` (user answered the prompt)
         *       | ``cancelling``
         *     * ``cancelling`` → ``cancelled``
         *     * ``failed`` / ``cancelled`` → ``pending`` on retry (new ``attempt_index``)
         *
         *     Succeeded tasks are terminal.
         * @enum {string}
         */
        BackgroundTaskStatus: "pending" | "running" | "cancelling" | "cancelled" | "succeeded" | "failed" | "suspended_waiting_user";
        /**
         * BackgroundTaskTriggerSource
         * @description How a task was launched. Used for auditing and dispatcher metrics.
         * @enum {string}
         */
        BackgroundTaskTriggerSource: "planner" | "classifier" | "user" | "manual" | "rule" | "schedule";
        /**
         * ChatDisplayMessage
         * @description Typed read model for chat history and display timeline messages.
         */
        ChatDisplayMessage: {
            /**
             * Allow Trace Collapse
             * @default false
             */
            allow_trace_collapse: boolean;
            /**
             * Attachments
             * @default null
             */
            attachments: {
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
            label: {
                [key: string]: unknown;
            } | null;
            /**
             * Message Id
             * @default null
             */
            message_id: string | null;
            /**
             * Message Kind
             * @default null
             */
            message_kind: string | null;
            /**
             * Payload
             * @default null
             */
            payload: {
                [key: string]: unknown;
            } | null;
            /**
             * Persona Id
             * @default null
             */
            persona_id: string | null;
            /**
             * Reply To
             * @default null
             */
            reply_to: {
                [key: string]: unknown;
            } | null;
            /** Role */
            role: string;
            /**
             * Run State
             * @default null
             */
            run_state: {
                [key: string]: unknown;
            } | null;
            /** Timestamp */
            timestamp: number;
            /**
             * Trace Available
             * @default false
             */
            trace_available: boolean;
            /**
             * Trace Display Mode
             * @default null
             */
            trace_display_mode: string | null;
            /**
             * Trace Summary
             * @default null
             */
            trace_summary: {
                [key: string]: unknown;
            } | null;
            /**
             * Turn Id
             * @default null
             */
            turn_id: string | null;
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
            history_version: number;
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
            workspace_path: string | null;
        };
        /** CostInfo */
        CostInfo: {
            /**
             * Input Tokens
             * @default null
             */
            input_tokens: number | null;
            /**
             * Output Tokens
             * @default null
             */
            output_tokens: number | null;
            /**
             * Usd
             * @default null
             */
            usd: number | null;
        };
        /** DelegateResult */
        DelegateResult: {
            /** Adapter */
            adapter: string;
            /**
             * Applied
             * @default false
             */
            applied: boolean;
            /**
             * Applied At
             * @default null
             */
            applied_at: number | null;
            /** Applied Files */
            applied_files: string[];
            /**
             * Artifact Registered
             * @default false
             */
            artifact_registered: boolean;
            /**
             * Cancelled
             * @default false
             */
            cancelled: boolean;
            cost: components["schemas"]["CostInfo"] | null;
            /** Delegation Id */
            delegation_id: string;
            /** Diff Path */
            diff_path: string | null;
            diff_stats: components["schemas"]["DiffStats"];
            /** Duration Ms */
            duration_ms: number;
            /** Error */
            error: string | null;
            /** Events Path */
            events_path: string;
            /** Exit Code */
            exit_code: number;
            /** Files Changed */
            files_changed: string[];
            /** Logs Path */
            logs_path: string;
            /** Success */
            success: boolean;
            /** Summary */
            summary: string | null;
        };
        /** DiffStats */
        DiffStats: {
            /**
             * Additions
             * @default 0
             */
            additions: number;
            /**
             * Deletions
             * @default 0
             */
            deletions: number;
            /**
             * Files Changed
             * @default 0
             */
            files_changed: number;
        };
        /** RunEvent */
        RunEvent: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "stdout" | "stderr" | "tool_call" | "tool_result" | "assistant_text" | "thinking" | "status" | "error";
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Ts Ms */
            ts_ms: number;
        };
        /**
         * RunTrigger
         * @description Describes how / why a run was started.
         *
         *     Carried on ``AgentRun.trigger`` so observability, delivery, and retract
         *     propagation can preserve provenance.
         */
        RunTrigger: {
            /** Correlation */
            correlation: string[];
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Priority */
            priority: string;
            /** Requester */
            requester: string;
            /** Source Channel */
            source_channel: string | null;
            /** Trigger Type */
            trigger_type: string;
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
