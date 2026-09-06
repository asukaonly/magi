import { useTranslation } from 'react-i18next';
import type { PortraitDisplayItem } from './portraitGrouping';

export const PortraitEvidenceLabel = ({ item }: { item: PortraitDisplayItem }) => {
  const { t } = useTranslation('app');
  if (!item.evidenceBasis) return null;
  return <span className="block text-xs font-normal leading-5 text-[hsl(var(--memory-muted))]">{t(`memory.provenance.${item.evidenceBasis}`)} · {t('memory.provenance.sources', { count: item.basisCount ?? 0 })}</span>;
};

export const portraitItemText = (item: PortraitDisplayItem, t: (key: string, options: Record<string, unknown>) => string): string => item.expression
  ? t(`memory.provenance.behavior_${item.expression.horizon}`, { value: item.expression.value })
  : item.text;
