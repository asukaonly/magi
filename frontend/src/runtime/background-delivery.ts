import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';
import { getRuntimeConfig } from './config';

const count = z.number().int().nonnegative().safe();
const statusSchema = z.object({
  queue: z.object({ pending: count, failed: count, bytes: count, next_retry_at_ms: z.number().nullable(), last_error: z.string().nullable() }),
  notification_read_ids: z.array(z.number().int().positive().safe()),
});
export type BackgroundDeliveryStatus = z.infer<typeof statusSchema>;

/** Capture the destination before asynchronous work; never look up a new target on retry. */
export function deliveryDestination() {
  const runtime = getRuntimeConfig();
  if (!runtime.serverId || !runtime.profileId || !runtime.dataEpoch || runtime.connectionGeneration === undefined) {
    throw new Error('Background delivery requires an established connection');
  }
  return {
    scope: { profile_id: runtime.profileId, server_id: runtime.serverId, data_epoch: runtime.dataEpoch },
    generation: runtime.connectionGeneration,
  };
}

export async function enqueueNotificationRead(ids: number[]): Promise<void> {
  const destination = deliveryDestination();
  for (const notificationId of new Set(ids)) {
    z.number().int().positive().safe().parse(notificationId);
    const accepted = await invoke<unknown>('enqueue_background_event', { request: {
      ...destination, event_id: crypto.randomUUID(), stream: `notification:${notificationId}`,
      policy: 'latest', payload: { kind: 'notification_read', notification_id: notificationId },
    } });
    if (accepted !== true) throw new Error('Background event was not stored');
  }
}

export async function readBackgroundDeliveryStatus(): Promise<BackgroundDeliveryStatus> {
  return statusSchema.parse(await invoke<unknown>('background_delivery_status', deliveryDestination()));
}

export async function retryBackgroundDelivery(): Promise<void> {
  await invoke('retry_background_delivery', deliveryDestination());
}
