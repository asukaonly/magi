import { useTranslation } from 'react-i18next';

import {
  recordCountLabel,
  scopeLabel,
  warningLabel,
} from '@/components/settings/memory-data/presentation';

export function MemoryRecordCounts({
  counts,
}: {
  counts: Record<string, number>;
}) {
  const { t } = useTranslation('app');
  const entries = Object.entries(counts)
    .map(([key, count]) => ({ key, count, label: recordCountLabel(t, key) }))
    .filter((entry): entry is { key: string; count: number; label: string } => Boolean(entry.label));

  if (entries.length === 0) {
    return null;
  }

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
      {entries.map(({ key, count, label }) => (
        <div key={key} className="min-w-0">
          <dt className="truncate text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
            {count.toLocaleString()}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function MemoryRestoreScope({ scope }: { scope: string[] }) {
  const { t } = useTranslation('app');
  const labels = scope
    .map((item) => scopeLabel(t, item))
    .filter((item): item is string => Boolean(item));

  if (labels.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-1.5" aria-label={t('settings.memory.dataManagement.restore.scopeLabel')}>
      {labels.map((label) => (
        <span
          key={label}
          className="rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-xs text-foreground/85"
        >
          {label}
        </span>
      ))}
    </div>
  );
}

export function MemoryRestoreWarnings({ warnings }: { warnings: string[] }) {
  const { t } = useTranslation('app');

  if (warnings.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
      <div className="text-sm font-medium text-foreground">
        {t('settings.memory.dataManagement.restore.reviewWarnings')}
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-muted-foreground">
        {warnings.map((warning, index) => (
          <li key={`${warning}-${index}`}>{warningLabel(t, warning)}</li>
        ))}
      </ul>
    </div>
  );
}
