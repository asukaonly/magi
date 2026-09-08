// Generated from production response schemas. Run npm run contracts:generate.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** EntityChangeApplyRequest */
        EntityChangeApplyRequest: {
            command: components["schemas"]["EntityChangeCommand"];
            /** Expected Fingerprint */
            expected_fingerprint: string;
            /** Request Id */
            request_id: string;
        };
        /** EntityChangeCommand */
        EntityChangeCommand: {
            /** Entity Id */
            entity_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "type_correction" | "merge";
            /**
             * New Type
             * @default null
             */
            new_type: string | null;
            /**
             * Review Id
             * @default null
             */
            review_id: string | null;
            /**
             * Target Entity Id
             * @default null
             */
            target_entity_id: string | null;
        };
        /** EntityChangeImpact */
        EntityChangeImpact: {
            /** Affected Subjects */
            affected_subjects: number;
            /** Assertions */
            assertions: number;
            /** Claims */
            claims: number;
            /** Corrections */
            corrections: number;
            /** Mentions */
            mentions: number;
            /** Relationships */
            relationships: number;
            /** Source Bindings */
            source_bindings: number;
        };
        /** EntityChangePreview */
        EntityChangePreview: {
            command: components["schemas"]["EntityChangeCommand"];
            /** Correction History May Block Revert */
            correction_history_may_block_revert: boolean;
            entity: components["schemas"]["IdentityEntity"];
            /** Evidence Event Ids */
            evidence_event_ids: {
                [key: string]: string[];
            };
            /** Fingerprint */
            fingerprint: string;
            impact: components["schemas"]["EntityChangeImpact"];
            /** @default null */
            target: components["schemas"]["IdentityEntity"] | null;
        };
        /** EntityChangeResult */
        EntityChangeResult: {
            /** Current Type */
            current_type: string;
            /**
             * Derivation State
             * @default pending
             * @constant
             */
            derivation_state: "pending";
            /** Entity Id */
            entity_id: string;
            impact: components["schemas"]["EntityChangeImpact"];
            /**
             * Kind
             * @enum {string}
             */
            kind: "type_correction" | "merge";
            /** Operation Id */
            operation_id: string;
        };
        /** EntityIdentityAudit */
        EntityIdentityAudit: {
            /** Groups */
            groups: components["schemas"]["EntityIdentityAuditGroup"][];
            /** Total */
            total: number;
        };
        /** EntityIdentityAuditGroup */
        EntityIdentityAuditGroup: {
            /** Entities */
            entities: components["schemas"]["IdentityEntity"][];
            /** Name */
            name: string;
        };
        /** EntityReviewRejectRequest */
        EntityReviewRejectRequest: {
            /** Expected Version */
            expected_version: number;
        };
        /** EntityReviewRejectResult */
        EntityReviewRejectResult: {
            /** Review Id */
            review_id: string;
            /**
             * Status
             * @default rejected
             * @constant
             */
            status: "rejected";
        };
        /** EntityTypeReview */
        EntityTypeReview: {
            entity: components["schemas"]["IdentityEntity"];
            /** Evidence Event Ids */
            evidence_event_ids: string[];
            /** Proposed Type */
            proposed_type: string;
            /** Review Id */
            review_id: string;
            /** Version */
            version: number;
        };
        /** EntityTypeReviewList */
        EntityTypeReviewList: {
            /** Items */
            items: components["schemas"]["EntityTypeReview"][];
            /** Total */
            total: number;
        };
        /** IdentityEntity */
        IdentityEntity: {
            /** Canonical Name */
            canonical_name: string;
            /** Entity Id */
            entity_id: string;
            /** Entity Type */
            entity_type: string;
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
