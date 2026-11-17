import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';

export const thoughtSchema = z.object({
  id: z.string(), persona_id: z.string(), created_at: z.number(),
  status: z.enum(['active', 'dismissed', 'stale']),
  kind: z.enum(['perspective', 'self_review', 'open_question']),
  topic: z.string(), content: z.string(), applicability: z.string(),
  citations: z.array(z.object({ event_id: z.string(), quote: z.string() })),
});
const pageSchema = z.object({
  items: z.array(thoughtSchema), enabled: z.boolean(), sharing_enabled: z.boolean(),
  last_checked_at: z.number().nullable(), last_status: z.string().nullable(),
});
const detailSchema = z.object({
  thought: thoughtSchema,
  evidence: z.array(z.object({ event_id: z.string(), source: z.string(), content: z.string(), occurred_at: z.number(), session_id: z.string().nullable() })),
});
export type PersonaThought = z.infer<typeof thoughtSchema>;
export type PersonaThoughtDetail = z.infer<typeof detailSchema>;
const path = (personaId: string, id?: string) => `/personality/reflections/${encodeURIComponent(personaId)}${id ? `/${encodeURIComponent(id)}` : ''}`;

export const personaThoughtsApi = {
  share: async (signal?: AbortSignal) => z.object({ thought: thoughtSchema.nullable() }).parse(
    unwrapGatewayPayload(await api.post<unknown>('/personality/reflections/share', {}, { signal })),
  ).thought,
  list: async (personaId: string, signal?: AbortSignal) => {
    const result = pageSchema.parse(unwrapGatewayPayload(await api.get<unknown>(path(personaId), { signal })));
    if (result.items.some((item) => item.persona_id !== personaId)) throw new Error('Thought owner mismatch');
    return result;
  },
  get: async (personaId: string, id: string, signal?: AbortSignal) => {
    const result = detailSchema.parse(unwrapGatewayPayload(await api.get<unknown>(path(personaId, id), { signal })));
    if (result.thought.id !== id || result.thought.persona_id !== personaId) throw new Error('Thought identity mismatch');
    return result;
  },
  dismiss: async (personaId: string, id: string) => { await api.delete(path(personaId, id)); },
};
