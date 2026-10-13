import type {
  L2Assertion,
  L2PendingReview,
  MemoryDashboard,
  MemorySourceCount,
} from '@/api/modules/memory';
import type { SourceStatusItem, SourceStatusResponse } from '@/api/modules/sources';
import type { StoryItem } from '@/api/modules/memoryStories';
import { getPendingAssertionCopy, getPendingReviewCopy } from '@/utils/memory-assertion-copy';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { isMemoryUpdateStory } from '../storyFilters';

export type PendingOverviewItem =
  | {
      kind: 'review';
      id: string;
      title: string;
      body: string;
      status: string;
      updatedAt: number;
      payload: L2PendingReview;
    }
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
  eventCount: number | null;
  runtimeKnown: boolean;
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

const getSourceLabel = (source?: SourceStatusItem): string | null => {
  if (!source) {
    return null;
  }
  return (
    String(source.display_name_translated || '').trim()
    || String(source.display_name || '').trim()
    || String(source.source_name || '').trim()
    || null
  );
};

const matchesSource = (source: SourceStatusItem, key: string): boolean => (
  [source.source_name, source.contribution_id, source.plugin_id].map(sourceKey).includes(sourceKey(key))
);

export const buildSourceRows = (
  counts: MemorySourceCount[] | null,
  status?: SourceStatusResponse | null,
  t?: OverviewTranslateFn,
): SourceCoverageRow[] => {
  const sources = status?.sources || [];
  const keys = new Set((counts ?? []).map((count) => sourceKey(count.source)));
  for (const source of sources) {
    if (![...keys].some((key) => matchesSource(source, key))) keys.add(sourceKey(source.source_name));
  }
  return [...keys].filter(Boolean).map((key) => {
    const count = counts?.find((item) => sourceKey(item.source) === key);
    const matches = sources.filter((item) => matchesSource(item, key));
    const source = matches.length === 1 ? matches[0] : undefined;
    const commonLabel = getSourceLabel(matches[0]);
    const label = commonLabel && matches.every((item) => getSourceLabel(item) === commonLabel) ? commonLabel : null;
    const commonIcon = matches[0]?.icon;
    return {
      key,
      label: label || getMemorySourceLabel(t || ((item: string) => item), key),
      pluginId: source?.plugin_id ?? null,
      icon: matches.every((item) => item.icon === commonIcon) ? commonIcon ?? null : null,
      status: combinedSourceStatus(matches),
      eventCount: counts === null ? null : count?.event_count ?? 0,
      runtimeKnown: Boolean(source),
      lastResultCount: source?.last_result_count ?? source?.last_raw_result_count ?? null,
      enabled: matches.length ? matches.some((item) => item.enabled) : null,
      running: matches.length ? matches.some((item) => item.running) : null,
      lastSyncAt: source?.last_sync_at ?? null,
      lastEventAt: count?.last_event_at ?? null,
    };
  }).sort((left, right) => (right.eventCount ?? 0) - (left.eventCount ?? 0) || left.label.localeCompare(right.label));
};

export const combinedSourceStatus = (sources: SourceStatusItem[]): string => {
  if (!sources.length) return 'unknown';
  const statuses = sources.map((source) => source.status || (source.enabled === false ? 'disabled' : source.running ? 'running' : 'unknown'));
  return ['error', 'retrying', 'running', 'setup_required', 'stale', 'unknown', 'never_synced'].find((status) => statuses.includes(status))
    ?? (statuses.includes('ready') ? 'ready' : statuses.every((status) => status === 'disabled') ? 'disabled' : 'unknown');
};

export const buildPendingItems = (
  dashboard: MemoryDashboard | null,
  stories: StoryItem[],
  reviews: L2PendingReview[],
  dismissedIds: Set<string>,
  t: OverviewTranslateFn,
): PendingOverviewItem[] => {
  const reviewItems: PendingOverviewItem[] = reviews.map((review) => {
    const copy = getPendingReviewCopy(review, t);
    return {
      kind: 'review',
      id: `review:${review.review_id}`,
      title: copy.title,
      body: copy.body,
      status: review.status,
      updatedAt: review.updated_at,
      payload: review,
    };
  });
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
  return [...reviewItems, ...assertionItems, ...storyItems]
    .filter((item) => !dismissedIds.has(item.id))
    .sort((left, right) => {
      const leftPriority = left.kind === 'review' ? 0 : left.kind === 'assertion' && left.status === 'contradicted' ? 1 : left.kind === 'story' ? 2 : 3;
      const rightPriority = right.kind === 'review' ? 0 : right.kind === 'assertion' && right.status === 'contradicted' ? 1 : right.kind === 'story' ? 2 : 3;
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
    case 'unknown':
      return 'bg-[hsl(var(--memory-muted))]';
    default:
      return 'bg-emerald-500';
  }
};

export const sourceStatusLabel = (status: string, t: OverviewTranslateFn): string => {
  const key = `memory.overview.sourceStatus.${status}`;
  const label = t(key);
  return label === key ? t('memory.sourcesPage.unknown') : label;
};
