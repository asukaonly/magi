import { useTranslation } from 'react-i18next';
import type { PortraitDisplayItem } from './portraitGrouping';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { portraitEvidenceIds } from '@/domain/memory/evidence';

export const PortraitEvidenceLabel = ({ item, onChanged }: { item: PortraitDisplayItem; onChanged?: () => void }) => {
  const { t } = useTranslation('app');
  return <span className="block text-xs font-normal leading-5 text-[hsl(var(--memory-muted))]">
    {item.evidenceBasis ? <span>{t(`memory.provenance.${item.evidenceBasis}`)} · {t('memory.provenance.sources', { count: item.basisCount ?? 0 })}</span> : null}
    <MemoryEvidenceButton target={{ title: item.text, recordRef: item.assertionId ? { kind: 'assertion', id: item.assertionId } : undefined, eventIds: portraitEvidenceIds(item.basisRefs), source: item.source, occurredAt: item.updatedAt }} onChanged={onChanged} />
  </span>;
};

export const portraitItemText = (item: PortraitDisplayItem, t: (key: string, options: Record<string, unknown>) => string): string => item.expression
  ? t(`memory.provenance.behavior_${item.expression.horizon}`, { value: item.expression.value })
  : item.text;
