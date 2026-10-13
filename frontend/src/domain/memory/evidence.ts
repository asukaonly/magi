export interface MemoryRecordRef {
  kind: 'event' | 'assertion' | 'relationship';
  id: string;
}

export interface MemoryEvidenceTarget {
  title: string;
  recordRef?: MemoryRecordRef;
  eventIds?: string[];
  source?: string | null;
  occurredAt?: number | null;
}

export function parseMemoryRecordRef(value: unknown): MemoryRecordRef | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (record.kind !== 'event' && record.kind !== 'assertion' && record.kind !== 'relationship') return undefined;
  if (typeof record.id !== 'string' || !record.id.trim()) return undefined;
  return { kind: record.kind, id: record.id };
}

export function memoryEvidenceIds(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((id): id is string => typeof id === 'string' && Boolean(id.trim())))]: [];
}

export function portraitEvidenceIds(refs: string[] | undefined): string[] {
  return memoryEvidenceIds(refs).filter((ref) => ref.startsWith('event:')).map((ref) => ref.slice(6));
}

export function searchEvidenceTarget(item: Record<string, unknown>, title: string): MemoryEvidenceTarget {
  const reference = typeof item.assertion_id === 'string' ? { kind: 'assertion', id: item.assertion_id }
    : typeof item.triple_id === 'string' ? { kind: 'relationship', id: item.triple_id }
      : typeof item.event_id === 'string' ? { kind: 'event', id: item.event_id } : item.record_ref;
  return {
    title,
    recordRef: parseMemoryRecordRef(reference),
    eventIds: memoryEvidenceIds(item.evidence_event_ids ?? item.evidence_events ?? item.source_event_ids),
    source: typeof item.source === 'string' ? item.source : null,
    occurredAt: typeof item.timestamp === 'number' ? item.timestamp : null,
  };
}
