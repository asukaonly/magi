import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';

const identifier = z.string().trim().min(1).max(1024);
export const endpointRefSchema = z.strictObject({
  connection_id: identifier.nullable(), contribution_id: identifier,
  target_id: identifier, thread_id: identifier.nullable(), device_id: identifier.nullable(),
});
export const endpointCatalogSchema = z.object({ endpoints: z.array(z.object({
  endpoint: endpointRefSchema, label: z.string(), available: z.boolean(),
  capabilities: z.array(z.enum(['message', 'audio', 'control'])),
})) });
export const deliveryPreferencesSchema = z.strictObject({targets: z.array(endpointRefSchema).max(32)});
export type EndpointRef = z.infer<typeof endpointRefSchema>;
export type EndpointView = z.infer<typeof endpointCatalogSchema>['endpoints'][number];
export const endpointKey = (value: EndpointRef): string => JSON.stringify([
  value.connection_id, value.contribution_id, value.target_id, value.thread_id, value.device_id,
]);

export const deliveryStatusSchema = z.object({deliveries: z.array(z.strictObject({
  delivery_id: identifier, message_id: identifier, session_id: identifier, endpoint: endpointRefSchema,
  state: z.enum(['pending', 'leased', 'sending', 'succeeded', 'uncertain', 'failed', 'expired', 'cancelled']),
  attempt_count: z.number().int().nonnegative(), updated_at_ms: z.number().int().nonnegative(),
}))});
export type DeliveryStatus = z.infer<typeof deliveryStatusSchema>['deliveries'][number];

export const channelEndpointsApi = {
  status: async (signal?: AbortSignal): Promise<DeliveryStatus[]> => deliveryStatusSchema.parse(
    unwrapGatewayPayload(await api.get<unknown>('/channels/delivery-status', {signal})),
  ).deliveries,
  list: async (signal?: AbortSignal): Promise<EndpointView[]> => endpointCatalogSchema.parse(
    unwrapGatewayPayload(await api.get<unknown>('/channels/endpoints', {signal})),
  ).endpoints,
  preferences: async (signal?: AbortSignal): Promise<EndpointRef[]> => deliveryPreferencesSchema.parse(
    unwrapGatewayPayload(await api.get<unknown>('/channels/delivery-preferences', {signal})),
  ).targets,
  save: async (targets: EndpointRef[]): Promise<EndpointRef[]> => deliveryPreferencesSchema.parse(
    unwrapGatewayPayload(await api.put<unknown>('/channels/delivery-preferences', {targets})),
  ).targets,
};
