import React from 'react';
import { Clock3, DatabaseZap, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';

import type { TimelineContentBlock, TimelineEventDetail, TimelineProjectionItem } from '@/api/modules/timeline';

interface TimelineFeedProps {
  items: TimelineProjectionItem[];
  expandedEventId: string | null;
  eventDetails: Record<string, TimelineEventDetail | undefined>;
  loadingDetailId: string | null;
  reanalyzingEventId: string | null;
  onToggleDetails: (eventId: string) => void;
  onReanalyze: (eventId: string) => Promise<void> | void;
}

const SOURCE_TONE: Record<string, string> = {
  browser_history: 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
  chrome_history: 'bg-orange-500/10 text-orange-700 dark:text-orange-300',
  manual_journal: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  chat: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  photo_library: 'bg-rose-500/10 text-rose-700 dark:text-rose-300',
};

const fallbackSourceLabel = (source: string) =>
  source
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const isEventItem = (item: TimelineProjectionItem): boolean => item.item_type === 'event';

const formatTimestamp = (value: number, language: string): string => {
  if (!value) {
    return '';
  }
  return new Date(value * 1000).toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const getRetentionKey = (mode: string | undefined): string => {
  if (mode === 'retain_raw') {
    return 'timeline.retention.retainRaw';
  }
  return 'timeline.retention.analyzeOnly';
};

const renderPreviewBlock = (block: TimelineContentBlock, index: number) => {
  if (block.kind === 'image') {
    return (
      <div
        key={`${block.kind}-${index}`}
        className="rounded-lg border border-dashed border-border/50 px-3 py-2 text-xs text-muted-foreground"
      >
        {block.value}
      </div>
    );
  }
  return (
    <p key={`${block.kind}-${index}`} className="text-sm leading-6 text-foreground/85">
      {block.value}
    </p>
  );
};

export const TimelineFeed: React.FC<TimelineFeedProps> = ({
  items,
  expandedEventId,
  eventDetails,
  loadingDetailId,
  reanalyzingEventId,
  onToggleDetails,
  onReanalyze,
}) => {
  const { t, i18n } = useTranslation('app');

  const getSourceLabel = (source: string) => {
    const key = `timeline.sources.${source}`;
    const translated = t(key);
    return translated === key ? fallbackSourceLabel(source) : translated;
  };

  if (items.length === 0) {
    return (
      <div className="flex min-h-[220px] items-center justify-center rounded-xl border border-dashed border-border/60 px-6 text-center">
        <div>
          <p className="text-sm font-medium text-foreground">{t('timeline.feed.emptyTitle')}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t('timeline.feed.emptyBody')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {items.map((item, index) => {
        const timestampLabel = formatTimestamp(item.sort_time, i18n.language);

        if (!isEventItem(item)) {
          const keyTopics = item.display_payload.key_topics || [];
          const keyEntities = item.display_payload.key_entities || [];

          return (
            <article
              key={item.item_id}
              className="grid gap-3 border-b border-border/50 py-4 sm:grid-cols-[104px_minmax(0,1fr)] sm:py-5"
            >
              <div className="relative hidden sm:block">
                <div className="pr-6 text-right">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                    {timestampLabel.split(' ').slice(0, 2).join(' ')}
                  </div>
                  <div className="mt-1 text-sm text-foreground/80">{timestampLabel.split(' ').slice(2).join(' ')}</div>
                </div>
                <span className="absolute right-0 top-1.5 h-2.5 w-2.5 translate-x-1/2 rounded-full border-2 border-background bg-secondary" />
                {index !== items.length - 1 ? (
                  <span className="absolute right-0 top-5 h-[calc(100%+1.5rem)] w-px bg-border/70" />
                ) : null}
              </div>

              <div className="min-w-0 space-y-3 rounded-2xl border border-border/50 bg-muted/20 px-4 py-4">
                <div className="flex flex-wrap items-center gap-2 sm:hidden">
                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Clock3 className="h-3.5 w-3.5" />
                    {timestampLabel}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary" className="rounded-full text-[11px]">
                    {t('timeline.feed.summaryBadge')}
                  </Badge>
                  <Badge variant="outline" className="rounded-full text-[11px]">
                    {t('timeline.feed.sourceEventCount', { count: item.display_payload.source_event_count || 0 })}
                  </Badge>
                </div>

                <div className="space-y-1.5">
                  <h2 className="text-base font-semibold tracking-tight text-foreground sm:text-[1.05rem]">
                    {item.display_payload.title || item.item_id}
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">{item.display_payload.summary || ''}</p>
                </div>

                {(keyTopics.length > 0 || keyEntities.length > 0) ? (
                  <div className="flex flex-wrap gap-2">
                    {keyTopics.map((topic) => (
                      <span key={topic} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        #{topic}
                      </span>
                    ))}
                    {keyEntities.map((entity) => (
                      <span
                        key={entity}
                        className="rounded-full border border-border/50 px-2 py-0.5 text-[11px] text-foreground/80"
                      >
                        {entity}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </article>
          );
        }

        const eventId = item.primary_event_id || item.source_event_ids[0] || item.item_id;
        const detail = eventDetails[eventId];
        const sourceType = item.display_payload.source_type || 'memory';
        const contentBlocks = item.display_payload.content_blocks || [];
        const tags = item.display_payload.tags || [];
        const entities = item.display_payload.entities || [];
        const isExpanded = expandedEventId === eventId;

        return (
          <article key={item.item_id} className="grid gap-3 border-b border-border/50 py-4 sm:grid-cols-[104px_minmax(0,1fr)] sm:py-5">
            <div className="relative hidden sm:block">
              <div className="pr-6 text-right">
                <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                  {timestampLabel.split(' ').slice(0, 2).join(' ')}
                </div>
                <div className="mt-1 text-sm text-foreground/80">{timestampLabel.split(' ').slice(2).join(' ')}</div>
              </div>
              <span className="absolute right-0 top-1.5 h-2.5 w-2.5 translate-x-1/2 rounded-full border-2 border-background bg-primary" />
              {index !== items.length - 1 ? (
                <span className="absolute right-0 top-5 h-[calc(100%+1.5rem)] w-px bg-border/70" />
              ) : null}
            </div>

            <div className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center gap-2 sm:hidden">
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" />
                  {timestampLabel}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Badge className={cn('rounded-full border-0 text-[11px]', SOURCE_TONE[sourceType] || 'bg-muted text-foreground')}>
                  {getSourceLabel(sourceType)}
                </Badge>
                <Badge variant="secondary" className="rounded-full text-[11px]">
                  {t(getRetentionKey(item.display_payload.retention_mode))}
                </Badge>
              </div>

              <div className="space-y-1.5">
                <h2 className="text-base font-semibold tracking-tight text-foreground sm:text-[1.05rem]">
                  {item.display_payload.title || eventId}
                </h2>
                <p className="text-sm leading-6 text-muted-foreground">{item.display_payload.summary || ''}</p>
              </div>

              {(tags.length > 0 || entities.length > 0) ? (
                <div className="flex flex-wrap gap-2">
                  {tags.map((tag) => (
                    <span key={tag} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                      #{tag}
                    </span>
                  ))}
                  {entities.map((entity) => (
                    <span
                      key={`${entity.id || entity.label || 'entity'}-${entity.type || 'unknown'}`}
                      className="rounded-full border border-border/50 px-2 py-0.5 text-[11px] text-foreground/80"
                    >
                      {entity.label || entity.id || t('timeline.feed.unknownEntity')}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2.5 text-muted-foreground hover:text-foreground"
                  onClick={() => onToggleDetails(eventId)}
                  aria-label={isExpanded ? t('timeline.feed.hideDetails') : t('timeline.feed.showDetails')}
                >
                  {isExpanded ? t('timeline.feed.hideDetails') : t('timeline.feed.showDetails')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2.5 text-muted-foreground hover:text-foreground"
                  onClick={() => void onReanalyze(eventId)}
                  disabled={reanalyzingEventId === eventId}
                  aria-label={t('timeline.feed.reanalyze')}
                >
                  <RefreshCw className={cn('mr-2 h-3.5 w-3.5', reanalyzingEventId === eventId && 'animate-spin')} />
                  {t('timeline.feed.reanalyze')}
                </Button>
              </div>

              {isExpanded ? (
                <div className="space-y-5 border-t border-border/50 pt-4">
                  {loadingDetailId === eventId && !detail ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <LoadingSpinner className="h-4 w-4" />
                      {t('timeline.feed.loadingDetails')}
                    </div>
                  ) : (
                    <>
                      <section className="space-y-2">
                        <h3 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                          {t('timeline.feed.detailTitle')}
                        </h3>
                        <div className="space-y-2">{(detail?.content_blocks || contentBlocks).map(renderPreviewBlock)}</div>
                      </section>

                      <div className="grid gap-4 lg:grid-cols-2">
                        <section className="space-y-2">
                          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                            <DatabaseZap className="h-3.5 w-3.5" />
                            {t('timeline.feed.retentionTitle')}
                          </div>
                          <div className="space-y-1 text-sm text-muted-foreground">
                            <p>{t(getRetentionKey(detail?.retention?.mode || item.display_payload.retention_mode))}</p>
                            <p>{detail?.retention?.raw_payload_ref || item.display_payload.raw_payload_ref || t('timeline.feed.noRawPayload')}</p>
                          </div>
                        </section>

                        <section className="space-y-2">
                          <h3 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                            {t('timeline.feed.derivedTitle')}
                          </h3>
                          {detail?.graph_evidence && detail.graph_evidence.length > 0 ? (
                            <div className="space-y-2">
                              {detail.graph_evidence.map((edge) => (
                                <div
                                  key={`${edge.subject_id}-${edge.predicate}-${edge.object_id}`}
                                  className="rounded-xl border border-border/50 px-3 py-2"
                                >
                                  <div className="flex flex-wrap items-center gap-2 text-sm text-foreground">
                                    <span>{edge.subject_id}</span>
                                    <Badge variant="secondary" className="rounded-full text-[11px]">
                                      {edge.predicate}
                                    </Badge>
                                    <span>{edge.object_id}</span>
                                  </div>
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {t('timeline.feed.evidenceCount', { count: edge.evidence_event_ids.length })}
                                  </p>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">{t('timeline.feed.noDerivedEvidence')}</p>
                          )}
                        </section>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
};

export default TimelineFeed;
