// Generated from production response schemas. Run npm run contracts:generate.
import type { components } from './device-types';
export declare function validateCollectionCapability(value: unknown): value is components['schemas']['CollectionCapability'];
export declare function validateCollectorScope(value: unknown): value is components['schemas']['CollectorScope'];
export declare function validateCollectorClaim(value: unknown): value is components['schemas']['CollectorClaim'];
export declare function validateCapabilityIdentity(value: unknown): value is components['schemas']['CapabilityIdentity'];
export declare function validateSourceObservation(value: unknown): value is components['schemas']['SourceObservation'];
export declare function validateDeliveryBatch(value: unknown): value is components['schemas']['DeliveryBatch'];
export declare function validateDeliveryReceipt(value: unknown): value is components['schemas']['DeliveryReceipt'];
