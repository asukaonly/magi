import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';
import { getRuntimeConfig } from '@/runtime/config';

export const maintenanceSchema = z.object({
  version: z.literal(2), kind: z.enum(['clear', 'restore']).nullable(), operation_id: z.string().nullable(),
  phase: z.enum(['idle', 'admitting', 'pending', 'draining', 'clearing', 'restoring', 'verifying', 'failed', 'completed']),
  content_epoch: z.string().min(1).max(128),
  data_epoch: z.string().min(1).max(128), result: z.unknown().nullable(), error: z.string().nullable(),
});
export type CenterMaintenance = z.infer<typeof maintenanceSchema>;
const infoSchema = z.object({
  server_id: z.string().uuid(), protocol_version: z.literal(2), service_ready: z.boolean(),
  maintenance: maintenanceSchema, plugin_execution: z.literal('server'),
});
const clientSchema = z.object({ client_id: z.string().uuid(), name: z.string(), created_at_ms: z.number(), revoked_at_ms: z.number().nullable() });

export const serverApi = {
  async info() {
    const info = infoSchema.parse(unwrapGatewayPayload(await api.get<unknown>('/server/info')));
    if (info.server_id !== getRuntimeConfig().serverId) throw new Error('Center identity changed');
    return info;
  },
  async maintenance(): Promise<CenterMaintenance> {
    return maintenanceSchema.parse(unwrapGatewayPayload(await api.get<unknown>('/server/maintenance')));
  },
  async operation(operationId: string): Promise<CenterMaintenance> {
    const status = maintenanceSchema.parse(unwrapGatewayPayload(await api.get<unknown>(`/server/maintenance/${encodeURIComponent(operationId)}`)));
    if (status.operation_id !== operationId) throw new Error('Maintenance operation identity changed');
    return status;
  },
  async restore(candidateId: string): Promise<CenterMaintenance> {
    const status = maintenanceSchema.parse(unwrapGatewayPayload(await api.post<unknown>(`/memory/portability/restores/${encodeURIComponent(candidateId)}/confirm`)));
    if (status.operation_id !== candidateId || status.kind !== 'restore') throw new Error('Restore operation identity changed');
    return status;
  },
  async clear(operationId: string): Promise<CenterMaintenance> {
    const status = maintenanceSchema.parse(unwrapGatewayPayload(await api.delete<unknown>('/memory/clear', {
      headers: { 'X-Magi-Full-Clear-Transaction': operationId },
    })));
    if (status.operation_id !== operationId) throw new Error('Maintenance operation identity changed');
    return status;
  },
  async clients() { return z.array(clientSchema).parse(unwrapGatewayPayload(await api.get<unknown>('/server/clients'))); },
  async revoke(clientId: string): Promise<void> { await api.delete(`/server/clients/${encodeURIComponent(clientId)}`); },
  async pairingGrant() {
    return z.object({ pairing_token: z.string(), expires_at_ms: z.number() }).parse(unwrapGatewayPayload(await api.post<unknown>('/server/pairing-grants')));
  },
};
