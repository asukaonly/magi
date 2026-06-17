import { type ComponentType, useEffect, useMemo, useState } from 'react';
import { Check, ClipboardCheck, Database, HardDrive, Plug, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { memoryApi, type L2Assertion, type MemoryDashboard, type MemorySourceCount } from '@/api/modules/memory';
import { sensorsApi, type SensorSourceStatusItem, type SensorSourceStatusResponse } from '@/api/modules/sensors';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
} from './MemoryPageFrame';

type PendingOverviewItem =
  | {
      kind: 'assertion';
      id: string;
      title: string;
      body: string;
      status: string;
      updatedAt: number;
      payload: L2Assertion;
    }
  | {
      kind: 'story';
      id: string;
      title: string;
      body: string;
      status: string;
      updatedAt: number;
      payload: StoryItem;
    };

interface SourceCoverageRow {
  key: string;
  label: string;
  eventCount: number;
  lastResultCount: number | null;
  enabled: boolean | null;
  running: boolean | null;
  lastSyncAt: number | string | null;
  lastEventAt: number | null;
}

type OverviewTranslateFn = (key: string, options?: Record<string, unknown>) => string;

const formatBytes = (bytes?: number | null): string => {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = unitIndex === 0 || size >= 10 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
};

const sourceKey = (value: string | null | undefined): string => String(value || '').trim().toLowerCase();

const formatInteger = (value: number): string => Number(value || 0).toLocaleString();

const timestampToDate = (value: number | string | null | undefined): Date | null => {
  if (value == null || value === '') {
    return null;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) {
      return null;
    }
    return new Date(value > 1_000_000_000_000 ? value : value * 1000);
  }
  const trimmed = String(value).trim();
  if (!trimmed) {
    return null;
  }
  const numeric = Number(trimmed);
  if (Number.isFinite(numeric)) {
    return timestampToDate(numeric);
  }
  const parsed = Date.parse(trimmed);
  return Number.isFinite(parsed) ? new Date(parsed) : null;
};

const formatOverviewTimestamp = (value: number | string | null | undefined, locale: string): string | null => {
  const date = timestampToDate(value);
  if (!date) {
    return null;
  }
  return new Intl.DateTimeFormat(locale || undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

const sanitizeMemoryText = (value: string, t: OverviewTranslateFn): string => {
  const chatLabel = getMemorySourceLabel(t, 'chat');
  return String(value || '').replace(/\bchat[_\s-]?projector\b/gi, chatLabel);
};

const storyDisplayTitle = (story: StoryItem, t: OverviewTranslateFn): string => {
  const title = sanitizeMemoryText(String(story.title || '').trim(), t);
  if (title) {
    return title;
  }
  const key = `memory.stories.categories.${story.summary_category}`;
  const translated = t(key);
  return translated !== key ? translated : story.summary_category;
};

const getSensorLabel = (sensor?: SensorSourceStatusItem): string | null => {
  if (!sensor) {
    return null;
  }
  return (
    String(sensor.display_name_translated || '').trim()
    || String(sensor.display_name || '').trim()
    || String(sensor.source_name || '').trim()
    || null
  );
};

const findSensorForSource = (
  source: MemorySourceCount,
  sensors: SensorSourceStatusItem[],
): SensorSourceStatusItem | undefined => {
  const sourceName = sourceKey(source.source);
  return sensors.find((sensor) => {
    const candidates = [
      sensor.source_name,
      sensor.contribution_id,
      sensor.plugin_id,
    ].map(sourceKey);
    return candidates.includes(sourceName);
  });
};

const buildSourceRows = (
  counts: MemorySourceCount[],
  status?: SensorSourceStatusResponse | null,
  t?: OverviewTranslateFn,
): SourceCoverageRow[] => {
  const sensors = status?.sources || [];
  const rows = counts.map((source) => {
    const sensor = findSensorForSource(source, sensors);
    return {
      key: source.source,
      label: getSensorLabel(sensor) || getMemorySourceLabel(t || ((key: string) => key), source.source),
      eventCount: source.event_count,
      lastResultCount: sensor?.last_result_count ?? sensor?.last_raw_result_count ?? null,
      enabled: sensor ? Boolean(sensor.enabled) : null,
      running: sensor?.running == null ? null : Boolean(sensor.running),
      lastSyncAt: sensor?.last_sync_at ?? sensor?.last_run_at ?? null,
      lastEventAt: source.last_event_at,
    };
  });
  const known = new Set(counts.map((item) => sourceKey(item.source)));
  sensors.forEach((sensor) => {
    const keys = [sensor.source_name, sensor.contribution_id, sensor.plugin_id].map(sourceKey);
    if (keys.some((key) => key && known.has(key))) {
      return;
    }
    rows.push({
      key: sensor.source_name,
      label: getSensorLabel(sensor) || getMemorySourceLabel(t || ((key: string) => key), sensor.source_name),
      eventCount: 0,
      lastResultCount: sensor.last_result_count ?? sensor.last_raw_result_count ?? null,
      enabled: Boolean(sensor.enabled),
      running: sensor.running == null ? null : Boolean(sensor.running),
      lastSyncAt: sensor.last_sync_at ?? sensor.last_run_at ?? null,
      lastEventAt: null,
    });
  });
  return rows.sort((left, right) => right.eventCount - left.eventCount || left.label.localeCompare(right.label));
};

const buildPendingItems = (
  dashboard: MemoryDashboard | null,
  stories: StoryItem[],
  dismissedIds: Set<string>,
  t: OverviewTranslateFn,
): PendingOverviewItem[] => {
  const assertionItems: PendingOverviewItem[] = (dashboard?.pending_assertions.items || []).map((assertion) => ({
    kind: 'assertion',
    id: `assertion:${assertion.assertion_id}`,
    title: assertion.trait_name,
    body: assertion.trait_value,
    status: assertion.validation_state,
    updatedAt: assertion.last_validated_at || assertion.first_inferred_at || 0,
    payload: assertion,
  }));
  const storyItems: PendingOverviewItem[] = stories
    .filter((story) => story.review_state === 'pending_confirmation')
    .map((story) => ({
      kind: 'story',
      id: `story:${story.summary_id}`,
      title: storyDisplayTitle(story, t),
      body: sanitizeMemoryText(story.content, t),
      status: story.review_state,
      updatedAt: story.updated_at || story.period_end || 0,
      payload: story,
    }));
  return [...assertionItems, ...storyItems]
    .filter((item) => !dismissedIds.has(item.id))
    .sort((left, right) => {
      const leftPriority = left.kind === 'assertion' && left.status === 'contradicted' ? 0 : left.kind === 'story' ? 1 : 2;
      const rightPriority = right.kind === 'assertion' && right.status === 'contradicted' ? 0 : right.kind === 'story' ? 1 : 2;
      return leftPriority - rightPriority || right.updatedAt - left.updatedAt;
    });
};

const buildRecentStories = (stories: StoryItem[], t: OverviewTranslateFn): StoryItem[] => {
  const seen = new Set<string>();
  const items: StoryItem[] = [];
  stories
    .filter((story) => story.review_state !== 'archived' && story.review_state !== 'pending_confirmation')
    .forEach((story) => {
      const contentKey = sanitizeMemoryText(story.content, t).replace(/\s+/g, ' ').trim().toLowerCase();
      const fallbackKey = `${story.summary_type}:${story.summary_category}:${story.period_start || ''}:${story.period_end || ''}`;
      const key = contentKey || fallbackKey;
      if (!key || seen.has(key)) {
        return;
      }
      seen.add(key);
      items.push(story);
    });
  return items.slice(0, 5);
};

export const MemoryOverviewPage = () => {
  const { t, i18n } = useTranslation('app');
  const [dashboard, setDashboard] = useState<MemoryDashboard | null>(null);
  const [sensorStatus, setSensorStatus] = useState<SensorSourceStatusResponse | null>(null);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set());
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [dashboardPayload, sensorPayload, storyPayload] = await Promise.all([
          memoryApi.getDashboard({ pending_limit: 8 }),
          sensorsApi.getStatus(),
          memoryStoriesApi.list({ limit: 12, offset: 0 }),
        ]);
        if (cancelled) {
          return;
        }
        setDashboard(dashboardPayload);
        setSensorStatus(sensorPayload);
        setStories(storyPayload.items || []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const sourceRows = useMemo(
    () => buildSourceRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );
  const pendingItems = useMemo(
    () => buildPendingItems(dashboard, stories, dismissedIds, t),
    [dashboard, stories, dismissedIds, t],
  );
  const recentStories = useMemo(
    () => buildRecentStories(stories, t),
    [stories, t],
  );
  const enabledSourceCount = sourceRows.filter((row) => row.enabled !== false).length;
  const processingBacklog = dashboard?.processing_backlog?.total_pending ?? 0;

  const dismissItem = (id: string) => {
    setDismissedIds((current) => new Set([...current, id]));
  };

  const handlePendingAction = async (item: PendingOverviewItem, action: 'confirmed' | 'rejected') => {
    setActionBusyId(item.id);
    try {
      if (item.kind === 'assertion') {
        await memoryApi.submitAssertionFeedback(item.payload.assertion_id, action);
      } else {
        await memoryStoriesApi.review(item.payload.summary_id, { review_state: action });
      }
      dismissItem(item.id);
    } finally {
      setActionBusyId(null);
    }
  };

  const metrics = [
    {
      key: 'total',
      label: t('memory.overview.metrics.totalMemories'),
      value: String(dashboard?.statistics.total_memories ?? 0),
      icon: Database,
    },
    {
      key: 'sources',
      label: t('memory.overview.metrics.sources'),
      value: String(enabledSourceCount),
      icon: Plug,
    },
    {
      key: 'pending',
      label: t('memory.overview.metrics.pending'),
      value: String(pendingItems.length),
      icon: ClipboardCheck,
    },
    {
      key: 'storage',
      label: t('memory.overview.metrics.storage'),
      value: formatBytes(dashboard?.statistics.disk_usage_bytes),
      icon: HardDrive,
    },
  ] satisfies Array<{ key: string; label: string; value: string; icon: ComponentType<{ className?: string }> }>;

  return (
    <MemoryPageFrame title={t('memory.overview.title')} description={t('memory.overview.subtitle')} hideHeader>
      {loading ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="flex items-center gap-2">
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.overview.empty.loading')}</span>
          </div>
        </section>
      ) : error ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.error')}</section>
      ) : (
        <div className="space-y-4">
          <section className="grid gap-3 md:grid-cols-4">
            {metrics.map((metric) => (
              <div key={metric.key} className={MEMORY_SECTION_CARD_CLASS}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-xs text-[hsl(var(--memory-muted))]">{metric.label}</div>
                    <div className="mt-2 text-2xl font-semibold text-[hsl(var(--memory-title))]">{metric.value}</div>
                  </div>
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.72)] text-[hsl(var(--memory-body))]">
                    <metric.icon className="h-4 w-4" />
                  </div>
                </div>
              </div>
            ))}
          </section>

          <section className={MEMORY_SECTION_CARD_CLASS}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.overview.sections.sources')}
              </h2>
              <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
                <span>{t('memory.overview.sourceCount', { count: sourceRows.length })}</span>
                <span className="text-[hsl(var(--memory-divider))]">/</span>
                <span>{t('memory.overview.processingBacklog', { count: processingBacklog })}</span>
              </div>
            </div>
            <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.6)]">
              {sourceRows.length > 0 ? (
                <>
                  <div className="hidden grid-cols-[minmax(0,1fr)_120px_180px] gap-2 pb-2 text-xs text-[hsl(var(--memory-muted))] md:grid">
                    <div>{t('memory.overview.sourceColumns.source')}</div>
                    <div>{t('memory.overview.sourceColumns.events')}</div>
                    <div>{t('memory.overview.sourceColumns.sync')}</div>
                  </div>
                  {sourceRows.map((row) => {
                    const syncLabel = formatOverviewTimestamp(row.lastSyncAt ?? row.lastEventAt, i18n.language)
                      || t('memory.overview.sourceStatus.noEvents');
                    return (
                      <div key={row.key} className="grid gap-2 py-3 md:grid-cols-[minmax(0,1fr)_120px_180px] md:items-center">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-[hsl(var(--memory-title))]">{row.label}</div>
                          <div className="text-xs text-[hsl(var(--memory-muted))]">
                            {row.enabled === false
                              ? t('memory.overview.sourceStatus.disabled')
                              : row.running
                                ? t('memory.overview.sourceStatus.running')
                                : t('memory.overview.sourceStatus.ready')}
                          </div>
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{formatInteger(row.eventCount)}</div>
                          <div className="text-xs text-[hsl(var(--memory-muted))] md:hidden">{t('memory.overview.sourceColumns.events')}</div>
                        </div>
                        <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                          <div>{syncLabel}</div>
                          {row.lastResultCount != null ? (
                            <div>{t('memory.overview.sourceLastResult', { count: row.lastResultCount })}</div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </>
              ) : (
                <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.sources')}</div>
              )}
            </div>
          </section>

          {pendingItems.length > 0 ? (
            <section className={MEMORY_SECTION_CARD_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
                  {t('memory.overview.sections.pending')}
                </h2>
                <span className="text-xs text-[hsl(var(--memory-muted))]">
                  {t('memory.overview.pendingCount', { count: pendingItems.length })}
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {pendingItems.map((item) => (
                  <div
                    key={item.id}
                    className="grid gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.55)] px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{item.title}</div>
                      <div className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{item.body}</div>
                      <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                        {item.kind === 'assertion' ? t('memory.overview.pendingKinds.assertion') : t('memory.overview.pendingKinds.story')}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className={MEMORY_ACTION_BUTTON_CLASS}
                        aria-label={item.kind === 'assertion' ? t('memory.overview.actions.confirmAssertion') : t('memory.overview.actions.confirmStory')}
                        disabled={actionBusyId === item.id}
                        onClick={() => void handlePendingAction(item, 'confirmed')}
                      >
                        <Check className="mr-1 h-3.5 w-3.5" />
                        {t('memory.overview.actions.confirm')}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className={MEMORY_ACTION_BUTTON_CLASS}
                        aria-label={item.kind === 'assertion' ? t('memory.overview.actions.rejectAssertion') : t('memory.overview.actions.rejectStory')}
                        disabled={actionBusyId === item.id}
                        onClick={() => void handlePendingAction(item, 'rejected')}
                      >
                        <X className="mr-1 h-3.5 w-3.5" />
                        {t('memory.overview.actions.reject')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className={MEMORY_SECTION_CARD_CLASS}>
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
              {t('memory.overview.sections.recent')}
            </h2>
            <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.6)]">
              {recentStories.length > 0 ? recentStories.map((story) => (
                <article key={story.summary_id} className="py-3">
                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                    {storyDisplayTitle(story, t)}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{sanitizeMemoryText(story.content, t)}</p>
                </article>
              )) : (
                <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.recent')}</div>
              )}
            </div>
          </section>
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryOverviewPage;
