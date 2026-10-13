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
export type ArchiveRecord = ArchiveSearchResult['items'][number];

async function searchArchives(params: { query?: string; offset?: number; limit: number; event_ids?: string[] }): Promise<ArchiveSearchResult> {
  const response = await api.get<unknown>('/memory/archives/search', {
    params,
    ...(params.event_ids ? { paramsSerializer: { indexes: null } } : {}),
  });
  return archiveSearchSchema.parse(unwrapGatewayPayload(response));
}

export const memoryArchivesApi = {
  search(query: string, offset = 0, limit = 20): Promise<ArchiveSearchResult> {
    return searchArchives({ query, offset, limit });
  },
  getEvents(eventIds: readonly string[]): Promise<ArchiveSearchResult> {
    const event_ids = [...new Set(eventIds)];
    if (event_ids.length === 0 || event_ids.length > 100) {
      return Promise.reject(new Error('Archive evidence requires between 1 and 100 event identifiers'));
    }
    return searchArchives({ event_ids, limit: event_ids.length });
  },
};
