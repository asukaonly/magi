import type { L2Assertion, MemoryDashboard, MemorySourceCount } from '@/api/modules/memory';
import type { SensorSourceStatusItem, SensorSourceStatusResponse } from '@/api/modules/sensors';
import type { StoryItem } from '@/api/modules/memoryStories';
import { getPendingAssertionCopy } from '@/utils/memory-assertion-copy';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { isMemoryUpdateStory } from '../storyFilters';

export type PendingOverviewItem =
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

export interface SourceCoverageRow {
  key: string;
  label: string;
  pluginId: string | null;
  icon: string | null;
  status: string;
  eventCount: number;
  lastResultCount: number | null;
  enabled: boolean | null;
  running: boolean | null;
  lastSyncAt: number | string | null;
  lastEventAt: number | null;
}

export type OverviewTranslateFn = (key: string, options?: Record<string, unknown>) => string;

export const formatBytes = (bytes?: number | null): string => {
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

export const formatInteger = (value: number): string => Number(value || 0).toLocaleString();

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

export const formatOverviewTimestamp = (value: number | string | null | undefined, locale: string): string | null => {
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

export const sanitizeMemoryText = (value: string, t: OverviewTranslateFn): string => {
  const chatLabel = getMemorySourceLabel(t, 'chat');
  return String(value || '').replace(/\bchat[_\s-]?projector\b/gi, chatLabel);
};

export const storyDisplayTitle = (story: StoryItem, t: OverviewTranslateFn): string => {
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

export const buildSourceRows = (
  counts: MemorySourceCount[],
  status?: SensorSourceStatusResponse | null,
  t?: OverviewTranslateFn,
): SourceCoverageRow[] => {
  const sensors = status?.sources || [];
  return counts.map((source) => {
    const sensor = findSensorForSource(source, sensors);
    return {
      key: source.source,
      label: getSensorLabel(sensor) || getMemorySourceLabel(t || ((key: string) => key), source.source),
      pluginId: sensor?.plugin_id ?? null,
      icon: sensor?.icon ?? null,
      status: sensor?.status || (sensor ? (sensor.enabled === false ? 'disabled' : 'ready') : 'ready'),
      eventCount: source.event_count,
      lastResultCount: sensor?.last_result_count ?? sensor?.last_raw_result_count ?? null,
      enabled: sensor ? Boolean(sensor.enabled) : null,
      running: sensor?.running == null ? null : Boolean(sensor.running),
      lastSyncAt: sensor?.last_sync_at ?? sensor?.last_run_at ?? null,
      lastEventAt: source.last_event_at,
    };
  }).sort((left, right) => right.eventCount - left.eventCount || left.label.localeCompare(right.label));
};

export const buildPendingItems = (
  dashboard: MemoryDashboard | null,
  stories: StoryItem[],
  dismissedIds: Set<string>,
  t: OverviewTranslateFn,
): PendingOverviewItem[] => {
  const assertionItems: PendingOverviewItem[] = (dashboard?.pending_assertions.items || []).map((assertion) => {
    const copy = getPendingAssertionCopy(assertion, t);
    return {
      kind: 'assertion',
      id: `assertion:${assertion.assertion_id}`,
      title: copy.title,
      body: copy.body,
      status: assertion.validation_state,
      updatedAt: assertion.last_validated_at || assertion.first_inferred_at || 0,
      payload: assertion,
    };
  });
  const storyItems: PendingOverviewItem[] = stories
    .filter((story) => story.review_state === 'pending_confirmation' && isMemoryUpdateStory(story))
    .map((story) => ({
      kind: 'story',
      id: `story:${story.summary_id}`,
      title: storyDisplayTitle(story, t),
      body: sanitizeMemoryText(story.detail_lead_text || story.content, t),
      status: story.review_state,
      updatedAt: story.display_timestamp || 0,
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

export const buildRecentStories = (stories: StoryItem[], t: OverviewTranslateFn): StoryItem[] => {
  const seen = new Set<string>();
  const items: StoryItem[] = [];
  stories
    .filter((story) => (
      story.review_state !== 'archived'
      && story.review_state !== 'pending_confirmation'
      && story.summary_feed_visible
    ))
    .forEach((story) => {
      const contentKey = sanitizeMemoryText(story.preview_text || story.content, t).replace(/\s+/g, ' ').trim().toLowerCase();
      const fallbackKey = `${story.summary_type}:${story.summary_category}:${story.display_timestamp || ''}`;
      const key = contentKey || fallbackKey;
      if (!key || seen.has(key)) {
        return;
      }
      seen.add(key);
      items.push(story);
    });
  return items.slice(0, 5);
};

export const sourceStatusDotClassName = (status: string): string => {
  switch (status) {
    case 'running':
      return 'bg-blue-500';
    case 'retrying':
    case 'stale':
      return 'bg-amber-500';
    case 'error':
      return 'bg-red-500';
    case 'disabled':
    case 'setup_required':
    case 'never_synced':
      return 'bg-[hsl(var(--memory-muted))]';
    default:
      return 'bg-emerald-500';
  }
};

export const sourceStatusLabel = (status: string, t: OverviewTranslateFn): string => {
  const key = `memory.overview.sourceStatus.${status}`;
  const label = t(key);
  return label === key ? t('memory.overview.sourceStatus.ready') : label;
};
