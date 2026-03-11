import React from 'react';
import { Clock3, DatabaseZap, RefreshCw, ScrollText } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription } from '@/components/ui/card';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';

import type { TimelineContentBlock, TimelineEventDetail, TimelineEventRecord } from '@/api/modules/timeline';

interface TimelineFeedProps {
  events: TimelineEventRecord[];
  expandedEventId: string | null;
  eventDetails: Record<string, TimelineEventDetail | undefined>;
  loadingDetailId: string | null;
  reanalyzingEventId: string | null;
  viewMode: 'comfortable' | 'compact';
  onToggleDetails: (eventId: string) => void;
  onReanalyze: (eventId: string) => Promise<void> | void;
}

const SOURCE_TONE: Record<string, string> = {
  browser_history: 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
  manual_journal: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  chat: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  photo_library: 'bg-rose-500/10 text-rose-700 dark:text-rose-300',
};

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

const getRetentionKey = (mode: string): string => {
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
        className="rounded-2xl border border-dashed border-border/40 bg-background/80 px-3 py-2 text-xs text-muted-foreground"
      >
        {block.value}
      </div>
    );
  }
  return (
    <p key={`${block.kind}-${index}`} className="text-sm leading-7 text-foreground/85">
      {block.value}
    </p>
  );
};

export const TimelineFeed: React.FC<TimelineFeedProps> = ({
  events,
  expandedEventId,
  eventDetails,
  loadingDetailId,
  reanalyzingEventId,
  viewMode,
  onToggleDetails,
  onReanalyze,
}) => {
  const { t, i18n } = useTranslation('app');

  if (events.length === 0) {
    return (
      <Card className="border-dashed border-border/40 bg-card/70">
        <CardContent className="flex min-h-[220px] flex-col items-center justify-center gap-3 text-center">
          <ScrollText className="h-8 w-8 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium text-foreground">{t('timeline.feed.emptyTitle')}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t('timeline.feed.emptyBody')}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {events.map((event) => {
        const isExpanded = expandedEventId === event.event_id;
        const detail = eventDetails[event.event_id];
        const paddingClass = viewMode === 'compact' ? 'p-5' : 'p-6';

        return (
          <Card
            key={event.event_id}
            className={cn(
              'overflow-hidden border-border/35 bg-card/80 shadow-sm transition-all',
              isExpanded && 'border-primary/30 shadow-md shadow-primary/5'
            )}
          >
            <CardContent className={paddingClass}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={cn('rounded-full border-0', SOURCE_TONE[event.source_type] || 'bg-muted text-foreground')}>
                  {t(`timeline.sources.${event.source_type}`)}
                </Badge>
                <Badge variant="secondary" className="rounded-full">
                  {t(getRetentionKey(event.retention?.mode || event.retention_mode))}
                </Badge>
                <span className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" />
                  {formatTimestamp(event.occurred_at, i18n.language)}
                </span>
              </div>

              <div className="mt-4">
                <h2 className="text-xl font-semibold tracking-tight text-foreground">{event.title}</h2>
                <p className="mt-2 text-sm leading-7 text-muted-foreground">{event.summary}</p>
              </div>

              {(event.tags.length > 0 || event.entities.length > 0) && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {event.tags.map((tag) => (
                    <span key={tag} className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                      #{tag}
                    </span>
                  ))}
                  {event.entities.map((entity) => (
                    <span
                      key={`${entity.id || entity.label || 'entity'}-${entity.type || 'unknown'}`}
                      className="rounded-full border border-border/40 px-2.5 py-1 text-xs text-foreground/85"
                    >
                      {entity.label || entity.id || t('timeline.feed.unknownEntity')}
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-5 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant={isExpanded ? 'secondary' : 'outline'}
                  onClick={() => onToggleDetails(event.event_id)}
                  aria-label={isExpanded ? t('timeline.feed.hideDetails') : t('timeline.feed.showDetails')}
                >
                  {isExpanded ? t('timeline.feed.hideDetails') : t('timeline.feed.showDetails')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => void onReanalyze(event.event_id)}
                  disabled={reanalyzingEventId === event.event_id}
                  aria-label={t('timeline.feed.reanalyze')}
                >
                  <RefreshCw className={cn('h-4 w-4', reanalyzingEventId === event.event_id && 'animate-spin')} />
                  {t('timeline.feed.reanalyze')}
                </Button>
              </div>

              {isExpanded && (
                <div className="mt-5 rounded-3xl border border-border/40 bg-background/70 p-5">
                  {loadingDetailId === event.event_id && !detail ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <LoadingSpinner className="h-4 w-4" />
                      {t('timeline.feed.loadingDetails')}
                    </div>
                  ) : (
                    <div className="space-y-5">
                      <div>
                        <h3 className="text-sm font-semibold text-foreground">{t('timeline.feed.detailTitle')}</h3>
                        <div className="mt-3 space-y-3">
                          {(detail?.content_blocks || event.content_blocks).map(renderPreviewBlock)}
                        </div>
                      </div>

                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="rounded-2xl border border-border/40 bg-card/70 p-4">
                          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                            <DatabaseZap className="h-4 w-4 text-primary" />
                            {t('timeline.feed.retentionTitle')}
                          </div>
                          <div className="mt-3 space-y-2 text-sm text-muted-foreground">
                            <p>{t(getRetentionKey(detail?.retention?.mode || event.retention?.mode || event.retention_mode))}</p>
                            <p>{detail?.retention?.raw_payload_ref || event.retention?.raw_payload_ref || event.raw_payload_ref || t('timeline.feed.noRawPayload')}</p>
                          </div>
                        </div>

                        <div className="rounded-2xl border border-border/40 bg-card/70 p-4">
                          <h3 className="text-sm font-semibold text-foreground">{t('timeline.feed.derivedTitle')}</h3>
                          {detail?.graph_evidence && detail.graph_evidence.length > 0 ? (
                            <div className="mt-3 space-y-3">
                              {detail.graph_evidence.map((edge) => (
                                <div key={`${edge.subject_id}-${edge.predicate}-${edge.object_id}`} className="rounded-2xl bg-background/80 p-3">
                                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                    <span>{edge.subject_id}</span>
                                    <Badge variant="secondary">{edge.predicate}</Badge>
                                    <span>{edge.object_id}</span>
                                  </div>
                                  <CardDescription className="mt-2">
                                    {t('timeline.feed.evidenceCount', { count: edge.evidence_event_ids.length })}
                                  </CardDescription>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="mt-3 text-sm text-muted-foreground">{t('timeline.feed.noDerivedEvidence')}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
};

export default TimelineFeed;
