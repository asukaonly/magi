import { MemoryEvidenceRecords } from '@/components/memory/evidence/MemoryEvidenceRecords';

export function EntityEvidence({ eventIds }: { eventIds: string[] }) {
  return <MemoryEvidenceRecords eventIds={eventIds} />;
}
