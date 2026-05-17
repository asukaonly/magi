import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Brain, X } from 'lucide-react';
import type { RecalledMemory } from '@/domain/chat/state';
import { cn } from '@/lib/utils';

const MAX_INLINE_CHIPS = 3;

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
};

export const RecalledMemoriesRow = ({ memories }: RecalledMemoriesRowProps) => {
  const { t, i18n } = useTranslation('app');
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const visibleChips = useMemo(() => memories.slice(0, MAX_INLINE_CHIPS), [memories]);
  const overflowCount = Math.max(0, memories.length - visibleChips.length);

  if (memories.length === 0) {
    return null;
  }

  const toggleExpand = (index: number) => {
    setExpandedIndex((prev) => (prev === index ? null : index));
  };

  const expandedMemory = expandedIndex != null ? memories[expandedIndex] ?? null : null;
  const expandedKindLabel = expandedMemory
    ? t(
        KIND_LABEL_KEY[expandedMemory.kind] ?? '',
        { defaultValue: expandedMemory.kind },
      )
    : '';
  const expandedRelative = expandedMemory ? formatRelativeTime(expandedMemory.occurredAt, i18n.language) : '';

  return (
    <div
      className="mt-3 flex flex-col gap-2 border-t border-border/40 pt-2.5 text-[11px]"
      data-testid="recalled-memories-row"
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-muted-foreground">
        <span className="inline-flex shrink-0 items-center gap-1.5 text-foreground/75">
          <Brain className="h-3 w-3" aria-hidden="true" />
          <span>
            {t('chat.recalledMemories.summary', {
              defaultValue: '调用了 {{count}} 条记忆',
              count: memories.length,
            })}
          </span>
        </span>
        {visibleChips.map((memory, index) => {
          const kindLabel = t(
            KIND_LABEL_KEY[memory.kind] ?? '',
            { defaultValue: memory.kind },
          );
          const isExpanded = expandedIndex === index;
          return (
            <button
              key={`${memory.sourceLayer}-${memory.topic}-${index}`}
              type="button"
              onClick={() => toggleExpand(index)}
              aria-expanded={isExpanded}
              className={cn(
                'group inline-flex max-w-[18rem] items-center gap-1 truncate rounded-sm px-1 py-0.5 text-left transition-colors',
                'hover:bg-foreground/5 hover:text-foreground/90',
                isExpanded && 'bg-foreground/5 text-foreground/95',
              )}
              title={`${memory.sourceLayer} · ${kindLabel} · ${memory.statement}`}
            >
              <span className="shrink-0 font-semibold tracking-[0.04em] text-foreground/70 group-hover:text-foreground/90">
                {memory.sourceLayer}
              </span>
              <span className="truncate">{memory.topic}</span>
            </button>
          );
        })}
        {overflowCount > 0 ? (
          <span className="inline-flex shrink-0 items-center text-muted-foreground/65">
            +{overflowCount}
          </span>
        ) : null}
      </div>
      {expandedMemory ? (
        <div
          className="flex flex-col gap-1.5 rounded-md border border-border/45 bg-background/60 px-2.5 py-2 text-[11.5px] leading-5"
          data-testid="recalled-memories-detail"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
              <span className="rounded-sm bg-primary/10 px-1.5 py-px font-mono text-[10px] font-semibold tracking-[0.04em] text-primary">
                {expandedMemory.sourceLayer}
              </span>
              <span className="text-foreground/75">{expandedKindLabel}</span>
              {expandedRelative ? <span aria-hidden="true">·</span> : null}
              {expandedRelative ? <span>{expandedRelative}</span> : null}
              {typeof expandedMemory.confidence === 'number' ? (
                <>
                  <span aria-hidden="true">·</span>
                  <span>
                    {t('chat.recalledMemories.confidence', {
                      defaultValue: '置信度 {{value}}',
                      value: expandedMemory.confidence.toFixed(2),
                    })}
                  </span>
                </>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => setExpandedIndex(null)}
              aria-label={t('chat.recalledMemories.close', { defaultValue: '收起记忆详情' })}
              className="shrink-0 rounded-sm p-0.5 text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground/90"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>
          <div className="text-foreground/90">{expandedMemory.statement}</div>
          {expandedMemory.evidenceText ? (
            <div className="rounded-sm border-l-2 border-primary/35 bg-muted/40 px-2 py-1 text-muted-foreground">
              {expandedMemory.evidenceText}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
