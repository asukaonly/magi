import { z } from 'zod';
import { api, unwrapGatewayPayload } from '../client';

const archiveRecordSchema = z.object({
  record_id: z.string().min(1),
  layer: z.enum(['l1', 'l3']),
  content: z.string(),
  source: z.string(),
  event_type: z.string(),
  occurred_at: z.number().finite(),
  period_end: z.number().finite().nullable(),
  archived_at: z.number().finite(),
  evidence_event_ids: z.array(z.string().min(1)),
  archived: z.literal(true),
});

export const archiveSearchSchema = z.object({
  items: z.array(archiveRecordSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(100),
  offset: z.number().int().min(0).max(10000),
  partial: z.boolean(),
  issues: z.array(z.object({
    code: z.enum(['archive_unreadable', 'archive_unsafe', 'record_invalid']),
    count: z.number().int().positive(),
  })),
});

export type ArchiveSearchResult = z.infer<typeof archiveSearchSchema>;

export const memoryArchivesApi = {
  async search(query: string, offset = 0, limit = 20): Promise<ArchiveSearchResult> {
    const response = await api.post<unknown>('/memory/archives/search', { query, offset, limit });
    return archiveSearchSchema.parse(unwrapGatewayPayload(response));
  },
};
