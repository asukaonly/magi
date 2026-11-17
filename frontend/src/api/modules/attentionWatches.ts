import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';

const fieldsSchema = z.object({ title: z.string().min(1), condition: z.string().min(1), sources: z.array(z.string().min(1)).min(1),
  expires_at: z.number().positive().nullable(), item_id: z.string().min(1).nullable() });
const watchSchema = fieldsSchema.extend({ id: z.string().min(1), version: z.number().int().positive(),
  status: z.enum(['active', 'paused', 'stopped', 'matched', 'expired']), created_at: z.number(), updated_at: z.number(),
  last_checked_at: z.number().nullable(), check_status: z.enum(['waiting', 'checking', 'no_match', 'matched', 'failed', 'invalidated']),
  result: z.object({ matched: z.literal(true), summary: z.string().min(1), next_step: z.string(),
    citations: z.array(z.object({ event_id: z.string().min(1), quote: z.string().min(1) })).min(1) }).nullable() });
const pageSchema = z.object({ items: z.array(watchSchema), sources: z.array(z.string().min(1)), next_offset: z.number().int().nonnegative().nullable() });
const mutationSchema = z.object({ watch: watchSchema.nullable(), replayed: z.boolean() });
export type AttentionWatch = z.infer<typeof watchSchema>;
export type WatchFields = z.infer<typeof fieldsSchema>;
export interface WatchMutation {
  request_id: string;
  action: 'create' | 'update' | 'pause' | 'resume' | 'stop' | 'delete';
  watch_id?: string;
  expected_version?: number;
  fields?: WatchFields;
}

export const attentionWatchesApi = {
  async list(offset: number, signal?: AbortSignal) {
    return pageSchema.parse(unwrapGatewayPayload(await api.get<unknown>('/personal-tasks/watches', { params: { offset }, signal })));
  },
  async get(id: string, signal?: AbortSignal) {
    const watch = watchSchema.parse(unwrapGatewayPayload(await api.get<unknown>(`/personal-tasks/watches/${encodeURIComponent(id)}`, { signal })));
    if (watch.id !== id) throw new Error('Attention watch identity mismatch');
    return watch;
  },
  async mutate(command: WatchMutation) {
    const result = mutationSchema.parse(unwrapGatewayPayload(await api.post<unknown>('/personal-tasks/watch-mutations', command)));
    if (command.watch_id && result.watch && command.watch_id !== result.watch.id) throw new Error('Attention watch identity mismatch');
    if (command.action !== 'delete' && !result.watch && !result.replayed) throw new Error('Attention watch mutation has no result');
    return result;
  },
};
