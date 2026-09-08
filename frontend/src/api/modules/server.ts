import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';
import { getRuntimeConfig } from '@/runtime/config';

export const maintenanceSchema = z.object({
  version: z.literal(1), operation_id: z.string().nullable(),
  phase: z.enum(['idle', 'pending', 'draining', 'clearing', 'failed', 'completed']),
  data_epoch: z.string().min(1).max(128), result: z.unknown().nullable(), error: z.string().nullable(),
});
export type CenterMaintenance = z.infer<typeof maintenanceSchema>;
const infoSchema = z.object({
  server_id: z.string().uuid(), protocol_version: z.literal(1), runtime_ready: z.boolean(),
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
