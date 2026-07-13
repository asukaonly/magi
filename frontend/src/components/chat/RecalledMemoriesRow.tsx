import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';
import type { RecalledMemory, RecalledMemorySummary } from '@/domain/chat/state';
import { cn } from '@/lib/utils';

const formatRelativeTime = (occurredAt: number | null | undefined, locale: string): string => {
  if (typeof occurredAt !== 'number' || !Number.isFinite(occurredAt)) {
    return '';
  }
  const occurredMs = occurredAt > 1e12 ? occurredAt : occurredAt * 1000;
  const diffMs = Date.now() - occurredMs;
  if (Math.abs(diffMs) < 60_000) {
    return new Intl.RelativeTimeFormat(locale || undefined, { numeric: 'auto' }).format(0, 'minute');
  }
  const diffSeconds = -Math.round(diffMs / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale || undefined, { numeric: 'auto' });
  const absMinutes = Math.abs(diffSeconds) / 60;
  if (absMinutes < 60) {
    return formatter.format(Math.round(diffSeconds / 60), 'minute');
  }
  if (absMinutes < 60 * 24) {
    return formatter.format(Math.round(diffSeconds / 3600), 'hour');
  }
  if (absMinutes < 60 * 24 * 7) {
    return formatter.format(Math.round(diffSeconds / 86_400), 'day');
  }
  if (absMinutes < 60 * 24 * 30) {
    return formatter.format(Math.round(diffSeconds / 604_800), 'week');
  }
  return formatter.format(Math.round(diffSeconds / 2_592_000), 'month');
};

const KIND_LABEL_KEY: Record<string, string> = {
  relationship: 'chat.recalledMemories.kinds.relationship',
  assertion: 'chat.recalledMemories.kinds.assertion',
  event: 'chat.recalledMemories.kinds.event',
  reflection: 'chat.recalledMemories.kinds.reflection',
  procedure: 'chat.recalledMemories.kinds.procedure',
};

type RecalledMemoriesRowProps = {
  memories: RecalledMemory[];
  summary?: RecalledMemorySummary;
};

export const RecalledMemoriesRow = ({ memories, summary }: RecalledMemoriesRowProps) => {
  const { t, i18n } = useTranslation('app');
  const [expanded, setExpanded] = useState(false);
  const detailId = useId();
  const detailRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (expanded && detailRef.current) {
      detailRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [expanded]);

  const hasExhaustiveStructuredCoverage = summary?.canClaimTotal === true
    && summary.coverageKind === 'exhaustive';
  const totalCount = summary?.totalCount ?? memories.length;
  const hasAdditionalCoverage = hasExhaustiveStructuredCoverage && totalCount > memories.length;
  const summaryText = t('chat.recalledMemories.summary', {
    defaultValue: '{{count}} 条记忆引用',
    count: memories.length,
  });

  if (memories.length === 0 && !hasExhaustiveStructuredCoverage) {
    return null;
  }

  if (memories.length === 0) {
    return (
      <div
        className="mt-2 text-xs leading-5 text-muted-foreground/75"
        data-testid="recalled-memories-row"
      >
        {t('chat.recalledMemories.exhaustiveSummary', {
          defaultValue: '已完整统计 {{count}} 条相关记录',
          count: totalCount,
        })}
      </div>
    );
  }

  return (
    <div
      className="flex flex-col text-xs"
      data-testid="recalled-memories-row"
    >
      <button
        type="button"
        aria-controls={detailId}
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
        className={cn(
          "relative -ml-1.5 inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-1 text-left text-muted-foreground/75 after:absolute after:inset-x-0 after:-inset-y-1.5 after:rounded-md after:content-['']",
          'transition-colors hover:bg-muted/35 hover:text-muted-foreground',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
        )}
      >
        <ChevronRight
          className={cn('h-3.5 w-3.5 shrink-0 transition-transform', expanded && 'rotate-90')}
          aria-hidden="true"
        />
        <span>{summaryText}</span>
      </button>
      {expanded ? (
        <div
          ref={detailRef}
          id={detailId}
          className="mt-1 space-y-2 border-l border-border/35 pl-4"
          data-testid="recalled-memories-detail"
        >
          {hasAdditionalCoverage ? (
            <div className="text-[11px] leading-5 text-muted-foreground/70">
              {t('chat.recalledMemories.coverageSummary', {
                defaultValue: '共找到 {{total}} 条相关记录，本次引用 {{shown}} 条',
                total: totalCount,
                shown: memories.length,
              })}
            </div>
          ) : null}
          {memories.map((memory, index) => {
            const kindLabel = t(
              KIND_LABEL_KEY[memory.kind] ?? '',
              { defaultValue: memory.kind },
            );
            const relativeTime = formatRelativeTime(memory.occurredAt, i18n.language);
            const metadata = [kindLabel, memory.topic, relativeTime].filter(Boolean).join(' · ');
            return (
              <div
                key={`${memory.kind}-${memory.topic}-${index}`}
                className="space-y-0.5 pr-2 text-left"
              >
                <div className="text-[11.5px] leading-5 text-foreground/85">{memory.statement}</div>
                {metadata ? (
                  <div className="text-[10.5px] leading-4 text-muted-foreground/65">{metadata}</div>
                ) : null}
                {memory.evidenceText ? (
                  <div className="pt-0.5 text-[10.5px] leading-4 text-muted-foreground/70">
                    {memory.evidenceText}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};
