import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';

export const personalTaskStatuses = ['inbox', 'active', 'waiting', 'someday', 'completed', 'cancelled'] as const;
const referenceSchema = z.object({
  kind: z.enum(['chat', 'memory', 'resource', 'run', 'source']), id: z.string(),
  label: z.string(), session_id: z.string().nullable(),
});
export const personalItemSchema = z.object({
  id: z.string(), user_id: z.string(), title: z.string(), body_md: z.string(),
  kind: z.enum(['action', 'project']), parent_id: z.string().nullable(),
  status: z.enum(personalTaskStatuses), origin: z.enum(['user', 'source']),
  defer_until: z.string().nullable(), due: z.string().nullable(), remind_at: z.string().nullable(),
  timezone: z.string(), references: z.array(referenceSchema), version: z.number().int().positive(),
  created_at: z.number(), updated_at: z.number(), closed_at: z.number().nullable(),
  reminder_revision: z.number().int(), reminder_synced_revision: z.number().int(), reminder_delivered_revision: z.number().int(),
});
const changeSchema = z.object({
  id: z.number().int(), item_id: z.string(), action: z.string(), actor: z.string(), version: z.number().int(),
  note: z.string(), changes: z.record(z.string(), z.unknown()), references: z.array(referenceSchema), created_at: z.number(),
});
const pageSchema = z.object({
  items: z.array(personalItemSchema), total: z.number().int(), next_offset: z.number().int().nullable(), counts: z.record(z.string(), z.number().int()),
});
const detailSchema = z.object({
  item: personalItemSchema, children: z.array(personalItemSchema), changes: z.array(changeSchema), next_history_offset: z.number().int().nullable(),
});
const mutationSchema = z.object({item: personalItemSchema.nullable(), deleted_ids: z.array(z.string()), replayed: z.boolean(), reminders_pending: z.boolean()});
export type PersonalItem = z.infer<typeof personalItemSchema>;
export type PersonalItemPage = z.infer<typeof pageSchema>;
export type PersonalItemDetail = z.infer<typeof detailSchema>;
export type PersonalTaskStatus = PersonalItem['status'];
export type PersonalTaskFields = Partial<Pick<PersonalItem,
  'title' | 'body_md' | 'kind' | 'parent_id' | 'status' | 'defer_until' | 'due' | 'remind_at' | 'timezone' | 'references'>>;
export interface PersonalTaskMutation {
  request_id: string;
  action: 'create' | 'update' | 'progress' | 'delete';
  item_id?: string;
  expected_version?: number;
  fields?: PersonalTaskFields;
  note?: string;
  cascade?: boolean;
}

export const personalTasksApi = {
  list: async (params: {view?: string; search?: string; parent_id?: string; offset?: number; limit?: number}, signal?: AbortSignal): Promise<PersonalItemPage> =>
    pageSchema.parse(unwrapGatewayPayload(await api.get<unknown>('/personal-tasks', {params, signal}))),
  get: async (id: string, signal?: AbortSignal, historyOffset = 0): Promise<PersonalItemDetail> => {
    const result = detailSchema.parse(unwrapGatewayPayload(await api.get<unknown>(`/personal-tasks/${encodeURIComponent(id)}`, {signal, params: {history_offset: historyOffset}})));
    if (result.item.id !== id) throw new Error('Personal item response identity mismatch');
    return result;
  },
  mutate: async (command: PersonalTaskMutation) => {
    const result = mutationSchema.parse(unwrapGatewayPayload(await api.post<unknown>('/personal-tasks/mutations', command)));
    if (command.item_id && (result.item ? result.item.id !== command.item_id : !result.deleted_ids.includes(command.item_id))) {
      throw new Error('Personal mutation response identity mismatch');
    }
    if (!result.item && result.deleted_ids.length === 0) throw new Error('Personal mutation response has no result');
    return result;
  },
};
