// Generated from production response schemas. Run npm run contracts:generate.
export interface paths {
    "/api/delivery/collector/{connection_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Collector Scope
         * @description Expose only the source protocol and generations, never center settings or secrets.
         */
        get: operations["collector_scope_collector__connection_id__get"];
        put?: never;
        /** Claim Collector */
        post: operations["claim_collector_collector__connection_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/delivery/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Deliver
         * @description ACK each fact only after its durable admission or idempotent materialization.
         */
        post: operations["deliver_events_post"];
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
        /** BackgroundEvent */
        BackgroundEvent: {
            /**
             * Event Id
             * Format: uuid
             */
            event_id: string;
            /** Occurred At Ms */
            occurred_at_ms: number;
            /** Payload */
            payload: components["schemas"]["PluginEvent"] | components["schemas"]["NotificationRead"] | components["schemas"]["SourceObservation"];
            /** Sequence */
            sequence: number;
            /** Stream */
            stream: string;
        };
        /** CapabilityIdentity */
        CapabilityIdentity: {
            /** Capability Id */
            capability_id: string;
            /**
             * Protocol
             * @constant
             */
            protocol: "source.change.v1";
            /** Schema Id */
            schema_id: string;
            /** Schema Version */
            schema_version: number;
        };
        /** CollectionCapability */
        CollectionCapability: {
            /** Capability Id */
            capability_id: string;
            /**
             * Direction
             * @default observe
             * @constant
             */
            direction?: "observe";
            /** Payload Schema */
            payload_schema: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /**
             * Protocol
             * @constant
             */
            protocol: "source.change.v1";
            /** Schema Id */
            schema_id: string;
            /** Schema Version */
            schema_version: number;
            /**
             * Supports Resources
             * @default false
             * @constant
             */
            supports_resources?: false;
        };
        /** CollectorClaim */
        CollectorClaim: {
            /** Capability Id */
            capability_id: string;
            /**
             * Connection Epoch
             * Format: uuid
             */
            connection_epoch: string;
            /**
             * Protocol
             * @constant
             */
            protocol: "source.change.v1";
            /** Schema Id */
            schema_id: string;
            /** Schema Version */
            schema_version: number;
        };
        /** CollectorScope */
        CollectorScope: {
            capability: components["schemas"]["CollectionCapability"];
            /** Claimed By */
            claimed_by: string | null;
            /**
             * Connection Epoch
             * Format: uuid
             */
            connection_epoch: string;
            /** Connection Id */
            connection_id: string;
            /** Source Type */
            source_type: string;
        };
        /** DeliveryBatch */
        DeliveryBatch: {
            /**
             * Data Epoch
             * Format: uuid
             */
            data_epoch: string;
            /** Events */
            events: components["schemas"]["BackgroundEvent"][];
            /**
             * Producer Id
             * Format: uuid
             */
            producer_id: string;
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** DeliveryReceipt */
        DeliveryReceipt: {
            /**
             * Data Epoch
             * Format: uuid
             */
            data_epoch: string;
            /** Receipts */
            receipts: components["schemas"]["EventReceipt"][];
            /**
             * Server Id
             * Format: uuid
             */
            server_id: string;
        };
        /** EventReceipt */
        EventReceipt: {
            /** Code */
            code: string;
            /**
             * Event Id
             * Format: uuid
             */
            event_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "accepted" | "retry" | "rejected";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        JsonValue: unknown;
        /** NotificationRead */
        NotificationRead: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "notification_read";
            /** Notification Id */
            notification_id: number;
        };
        /** ObservationChange */
        ObservationChange: {
            /** Object Id */
            object_id: string;
            /** Occurred At */
            occurred_at?: number | null;
            /**
             * Operation
             * @default upsert
             * @enum {string}
             */
            operation?: "upsert" | "delete";
            /** Payload */
            payload?: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Resources */
            resources?: components["schemas"]["ResourceRef"][];
            /** Version */
            version: string;
        };
        /** PluginEvent */
        PluginEvent: {
            /**
             * Connection Epoch
             * Format: uuid
             */
            connection_epoch: string;
            /** Connection Id */
            connection_id: string;
            /** Data */
            data: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Event Type */
            event_type: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "plugin_event";
            /** Plugin Target */
            plugin_target: string;
        };
        /**
         * ResourceRef
         * @description Opaque, revocable reference to host-managed content.
         */
        ResourceRef: {
            /** Connection Id */
            connection_id: string;
            /**
             * Display Name
             * @default
             */
            display_name?: string;
            /** Media Type */
            media_type: string;
            /** Resource Id */
            resource_id: string;
            /** Size Bytes */
            size_bytes: number;
            /** Version */
            version: string;
        };
        /** SourceObservation */
        SourceObservation: {
            /** Capability Id */
            capability_id: string;
            change: components["schemas"]["ObservationChange"];
            /**
             * Connection Epoch
             * Format: uuid
             */
            connection_epoch: string;
            /** Connection Id */
            connection_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "source_observation";
            /**
             * Protocol
             * @constant
             */
            protocol: "source.change.v1";
            /** Schema Id */
            schema_id: string;
            /** Schema Version */
            schema_version: number;
            /** Source Type */
            source_type: string;
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
    collector_scope_collector__connection_id__get: {
        parameters: {
            query?: never;
            header: {
                "x-magi-collector-source": string;
            };
            path: {
                connection_id: string;
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
                    "application/json": components["schemas"]["CollectorScope"];
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
    claim_collector_collector__connection_id__post: {
        parameters: {
            query?: never;
            header: {
                "x-magi-client-id": string;
                "x-magi-collector-source": string;
            };
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CollectorClaim"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CollectorScope"];
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
    deliver_events_post: {
        parameters: {
            query?: never;
            header: {
                "x-magi-client-id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeliveryBatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeliveryReceipt"];
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
