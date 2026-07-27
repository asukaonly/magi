/**
 * L1Tab - L1 Event Memory tab component
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { L1Event, MemoryStatistics } from '@/api/modules/memory';
import { formatTimestamp } from '@/hooks/useMemory';
import { cn } from '@/lib/utils';

interface L1TabProps {
  stats: MemoryStatistics['l1'];
  events: L1Event[];
  showStats?: boolean;
  showHeader?: boolean;
  formatSourceLabel?: (source: string) => string;
}

type MemoryTranslateFn = (key: string, options?: Record<string, unknown>) => string;
type EventDetailItem = { label: string; value: string };

const MEMORY_DOMAIN_KEYS: Record<string, string> = {
  '1': 'user_authored',
  '2': 'external_activity',
  '3': 'runtime_telemetry',
  '4': 'system_control',
  '5': 'interaction',
  user_authored: 'user_authored',
  external_activity: 'external_activity',
  runtime_telemetry: 'runtime_telemetry',
  system_control: 'system_control',
  interaction: 'interaction',
};

const RETENTION_CLASS_KEYS: Record<string, string> = {
  '1': 'disposable',
  '2': 'compressible',
  '3': 'permanent',
  disposable: 'disposable',
  compressible: 'compressible',
  permanent: 'permanent',
};

const INGEST_TARGET_KEYS: Record<string, string> = {
  '1': 'runtime_only',
  '2': 'l1_only',
  runtime_only: 'runtime_only',
  l1_only: 'l1_only',
};

const TOM_DEPTH_KEYS: Record<string, string> = {
  '1': 'none',
  '2': 'topology_only',
  '3': 'defensive_psychology',
  none: 'none',
  topology_only: 'topology_only',
  defensive_psychology: 'defensive_psychology',
};

const EMBEDDING_STATUS_KEYS: Record<string, string> = {
  ready: 'ready',
  pending: 'pending',
  failed: 'failed',
  skipped: 'skipped',
  disabled: 'disabled',
  stale: 'stale',
};

const SOURCE_METADATA_PRIORITY_KEYS = [
  'track_name',
  'artist_name',
  'album_name',
  'play_duration_sec',
  'track_duration_ms',
  'is_liked',
  'track_alias',
  'play_source',
  'netease_url',
  'title',
  'page_title',
  'url',
  'app_name',
  'window_title',
  'repository',
  'branch',
  'commit_message',
  'file_path',
];

const METADATA_LABEL_KEYS: Record<string, string> = {
  track_name: 'trackName',
  artist_name: 'artistName',
  album_name: 'albumName',
  play_duration_sec: 'playDuration',
  track_duration_ms: 'trackDuration',
  is_liked: 'liked',
  track_alias: 'trackAlias',
  play_source: 'playSource',
  netease_url: 'neteaseUrl',
  title: 'title',
  page_title: 'pageTitle',
  url: 'url',
  app_name: 'appName',
  window_title: 'windowTitle',
  repository: 'repository',
  branch: 'branch',
  commit_message: 'commitMessage',
  file_path: 'filePath',
  source_type: 'sourceType',
  source_app: 'sourceApp',
};

const OMITTED_METADATA_KEYS = new Set([
  'activity',
  'album_cover_url',
  'album_id',
  'artist_id',
  'captured_at',
  'content_blocks',
  'entities',
  'event_id',
  'id',
  'l2_batch_catch_up_owner',
  'l2_batch_max_estimated_tokens',
  'l2_batch_max_events',
  'l2_batch_max_wait_seconds',
  'l2_batch_min_ready_events',
  'l2_batch_owner',
  'memory_owner_user_id',
  'platform',
  'plugin_id',
  'privacy_labels',
  'processing_status',
  'projection',
  'raw_payload_ref',
  'retention_mode',
  'sensor_id',
  'source_item_id',
  'structured_entity_hints',
  'structured_graph_hints',
  'tags',
  'timeline',
  'track_id',
  'uid',
  'update_time',
  'user_id',
]);

const normalizeI18nKey = (value: string) => value
  .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  .replace(/[^a-zA-Z0-9]+/g, '_')
  .replace(/^_+|_+$/g, '')
  .toLowerCase();

const resolveTranslation = (t: MemoryTranslateFn, key: string): string | null => {
  const translated = t(key);
  return translated !== key ? translated : null;
};

const getMappedLabel = (
  t: MemoryTranslateFn,
  namespace: string,
  value: string | number | string[] | null | undefined,
  knownKeys: Record<string, string> = {}
): string | null => {
  if (Array.isArray(value)) {
    const labels: string[] = value
      .map((item) => getMappedLabel(t, namespace, item, knownKeys))
      .filter((label): label is string => Boolean(label));
    return labels.length > 0 ? labels.join(' · ') : null;
  }
  if (!hasDetailValue(value)) {
    return null;
  }
  const rawValue = String(value).trim();
  const key = knownKeys[rawValue.toLowerCase()] || normalizeI18nKey(rawValue);
  return resolveTranslation(t, `${namespace}.${key}`) || rawValue;
};

const getEventTypeLabel = (t: MemoryTranslateFn, value: string | null | undefined) => {
  if (!value) {
    return null;
  }
  const rawValue = String(value).trim();
  return resolveTranslation(t, `memory.eventTypes.${normalizeI18nKey(rawValue)}`) || rawValue;
};

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const getMetadataLabel = (t: MemoryTranslateFn, key: string) => {
  const mappedKey = METADATA_LABEL_KEYS[key] || normalizeI18nKey(key);
  const translated = resolveTranslation(t, `memory.l1.metadataLabels.${mappedKey}`);
  if (translated) {
    return translated;
  }
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const formatMetadataDuration = (t: MemoryTranslateFn, value: unknown, divisor = 1) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return null;
  }
  const seconds = Math.round(numericValue / divisor);
  if (seconds >= 60 && seconds % 60 === 0) {
    return `${seconds / 60}${t('memory.l1.metadataUnits.minutes')}`;
  }
  return `${seconds}${t('memory.l1.metadataUnits.seconds')}`;
};

const stringifyMetadataValue = (t: MemoryTranslateFn, key: string, value: unknown) => {
  if (value === null || value === undefined) {
    return null;
  }
  if (key === 'play_duration_sec') {
    return formatMetadataDuration(t, value);
  }
  if (key === 'track_duration_ms') {
    return formatMetadataDuration(t, value, 1000);
  }
  if (typeof value === 'boolean') {
    return value ? t('memory.l1.yes') : t('memory.l1.no');
  }
  if (Array.isArray(value)) {
    const items = value
      .map((item) => (typeof item === 'object' ? null : String(item).trim()))
      .filter((item): item is string => Boolean(item));
    return items.length > 0 ? items.join(' · ') : null;
  }
  if (typeof value === 'object') {
    return null;
  }
  const text = String(value).trim();
  return text || null;
};

const buildSourceMetadataHighlights = (t: MemoryTranslateFn, metadata: Record<string, unknown> | null) => {
  if (!metadata) {
    return [] as EventDetailItem[];
  }
  const timeline = isRecord(metadata.timeline) ? metadata.timeline : {};
  const provenance = isRecord(timeline.provenance)
    ? timeline.provenance
    : (isRecord(metadata.provenance) ? metadata.provenance : {});
  const highlights: EventDetailItem[] = [];
  const seen = new Set<string>();

  const add = (container: Record<string, unknown>, key: string) => {
    if (OMITTED_METADATA_KEYS.has(key)) {
      return;
    }
    const text = stringifyMetadataValue(t, key, container[key]);
    if (!text) {
      return;
    }
    const label = getMetadataLabel(t, key);
    const signature = `${label}:${text}`;
    if (!seen.has(signature)) {
      highlights.push({ label, value: text });
      seen.add(signature);
    }
  };

  SOURCE_METADATA_PRIORITY_KEYS.forEach((key) => {
    add(provenance, key);
    add(metadata, key);
  });
  Object.keys(provenance).forEach((key) => add(provenance, key));
  Object.keys(metadata).forEach((key) => add(metadata, key));

  return highlights;
};

const hasDetailValue = (value: string | number | null | undefined): value is string | number => {
  if (value === null || value === undefined) {
    return false;
  }
  return String(value).trim().length > 0;
};

const EventDetailField = ({
  label,
  value,
  monospace = false,
}: {
  label: string;
  value: string | number | null | undefined;
  monospace?: boolean;
}) => {
  if (!hasDetailValue(value)) {
    return null;
  }

  return (
    <div className="min-w-0 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.64)] px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">{label}</div>
      <div className={cn('mt-1 break-words text-sm leading-6 text-[hsl(var(--memory-title))]', monospace && 'font-mono text-xs')}>
        {String(value)}
      </div>
    </div>
  );
};

export const L1Tab: React.FC<L1TabProps> = ({ stats, events, showStats = true, showHeader = true, formatSourceLabel }) => {
  const { t } = useTranslation('app');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  const userAuthoredCount = events.filter((event) => event.author_type === 'user').length;
  const interactionCount = events.length - userAuthoredCount;

  const getSourceLabel = (source: string | null | undefined) => {
    if (!source) {
      return null;
    }
    return formatSourceLabel ? formatSourceLabel(source) : source;
  };

  return (
    <div className="space-y-4">
      {showStats ? (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{stats.event_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.totalEvents')}</div>
          </div>
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{userAuthoredCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.userAuthored')}</div>
          </div>
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{interactionCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.interaction')}</div>
          </div>
        </div>
      ) : null}

      <section className={cn(showHeader && 'border-t border-[hsl(var(--memory-divider)/0.72)] pt-4')}>
        {showHeader ? (
          <div className="mb-4 flex items-center gap-2">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--memory-title))]">
              <FileText className="h-5 w-5" />
              {t('memory.l1.events')}
            </h2>
          </div>
        ) : null}
        <div>
          {events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l1.noEvents')}
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
              {events.map((event, index) => {
                const isExpanded = expandedEventId === event.event_id;
                const sourceLabel = getSourceLabel(event.source);
                const eventTypeLabel = getEventTypeLabel(t, event.event_type) || event.event_type;
                const memoryDomainLabel = getMappedLabel(t, 'memory.l1.domains', event.memory_domain, MEMORY_DOMAIN_KEYS);
                const retentionLabel = getMappedLabel(t, 'memory.l1.retentionClasses', event.retention_class, RETENTION_CLASS_KEYS);
                const ingestTargetLabel = getMappedLabel(t, 'memory.l1.ingestTargets', event.ingest_target, INGEST_TARGET_KEYS);
                const tomDepthLabel = getMappedLabel(t, 'memory.l1.tomDepths', event.tom_depth, TOM_DEPTH_KEYS);
                const embeddingStatusLabel = getMappedLabel(t, 'memory.l1.embeddingStatuses', event.embedding_status, EMBEDDING_STATUS_KEYS);
                const authorTypeLabel = getMappedLabel(t, 'memory.l1.authorTypes', event.author_type);
                const contentTypeLabel = getMappedLabel(t, 'memory.l1.contentTypes', event.content_type);
                const metadata = isRecord(event.metadata_json) ? event.metadata_json : null;
                const metadataHighlights = buildSourceMetadataHighlights(t, metadata);
                const metadataJson = metadata ? JSON.stringify(metadata, null, 2) : null;
                const correlationId = event.correlation_id && event.correlation_id !== event.event_id
                  ? event.correlation_id
                  : null;
                const eventMeta = [sourceLabel, memoryDomainLabel]
                  .filter(Boolean)
                  .join(' · ');
                const importanceScore = Number.isFinite(event.importance_score)
                  ? event.importance_score.toFixed(2)
                  : undefined;

                return (
                  <article key={event.event_id} className={cn(index > 0 && 'border-t border-[hsl(var(--memory-divider)/0.52)]')}>
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-label={`${t('memory.l1.toggleEventDetails')}: ${eventTypeLabel} ${event.event_id}`}
                      onClick={() => setExpandedEventId((current) => (current === event.event_id ? null : event.event_id))}
                      className={cn(
                        'w-full text-left transition-colors',
                        isExpanded ? 'bg-[hsl(var(--memory-panel-subtle)/0.76)]' : 'hover:bg-[hsl(var(--memory-panel-subtle)/0.44)]'
                      )}
                    >
                      <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_180px_44px] md:items-center">
                        <div className="min-w-0">
                          <div className="flex min-w-0 items-center gap-2">
                            <Badge variant="outline" className="shrink-0 border-[hsl(var(--memory-border)/0.62)] bg-[hsl(var(--memory-panel-subtle)/0.72)] text-[hsl(var(--memory-title))]">
                              {eventTypeLabel}
                            </Badge>
                            {eventMeta ? (
                              <span className="truncate text-xs text-[hsl(var(--memory-muted))]">{eventMeta}</span>
                            ) : null}
                          </div>
                          <div className="mt-2 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-title))]">
                            {event.content}
                          </div>
                        </div>

                        <div className="text-xs text-[hsl(var(--memory-muted))] md:text-right">
                          {formatTimestamp(event.timestamp)}
                        </div>

                        <div className="flex justify-end">
                          <span className="flex h-8 w-8 items-center justify-center rounded-md border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.82)] text-[hsl(var(--memory-muted))]">
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </span>
                        </div>
                      </div>
                    </button>

                    {isExpanded ? (
                      <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.44)] px-4 py-4">
                        <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.64)] px-3 py-3">
                          <div className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                            {t('memory.l1.content')}
                          </div>
                          <div className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-title))]">
                            {event.content}
                          </div>
                        </div>

                        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                          <EventDetailField label={t('memory.l1.occurredAt')} value={formatTimestamp(event.timestamp)} />
                          <EventDetailField label={t('memory.l1.source')} value={sourceLabel} />
                          <EventDetailField label={t('memory.l1.memoryDomain')} value={memoryDomainLabel} />
                          <EventDetailField label={t('memory.l1.retentionClass')} value={retentionLabel} />
                          <EventDetailField label={t('memory.l1.embeddingStatus')} value={embeddingStatusLabel} />
                        </div>

                        {metadata ? (
                          <section className="mt-3 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.64)] px-3 py-3">
                            <div className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                              {t('memory.l1.sourceMetadata')}
                            </div>
                            {metadataHighlights.length > 0 ? (
                              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                {metadataHighlights.map((item) => (
                                  <div key={`${item.label}:${item.value}`} className="min-w-0 border-t border-[hsl(var(--memory-divider)/0.5)] pt-2 first:border-t-0 first:pt-0 sm:first:border-t sm:first:pt-2">
                                    <div className="text-xs text-[hsl(var(--memory-muted))]">{item.label}</div>
                                    <div className="mt-1 break-words text-sm leading-6 text-[hsl(var(--memory-title))]">{item.value}</div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                                {t('memory.l1.metadataTechnicalOnly')}
                              </div>
                            )}
                            <details className="mt-3 rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-3 py-2">
                              <summary className="cursor-pointer text-xs font-medium text-[hsl(var(--memory-muted))]">
                                {t('memory.l1.rawMetadata')}
                              </summary>
                              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[hsl(var(--memory-body))]">
                                {metadataJson}
                              </pre>
                            </details>
                          </section>
                        ) : null}

                        <details className="mt-3 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.64)] px-3 py-3">
                          <summary className="cursor-pointer text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                            {t('memory.l1.technicalIdentifiers')}
                          </summary>
                          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            <EventDetailField label={t('memory.l1.eventId')} value={event.event_id} monospace />
                            <EventDetailField label={t('memory.l1.sourceItemId')} value={event.source_item_id} monospace />
                            <EventDetailField label={t('memory.l1.idempotencyKey')} value={event.idempotency_key} monospace />
                            <EventDetailField label={t('memory.l1.correlationId')} value={correlationId} monospace />
                            <EventDetailField label={t('memory.l1.createdAt')} value={event.created_at ? formatTimestamp(event.created_at) : null} />
                            <EventDetailField label={t('memory.l1.ingestTarget')} value={ingestTargetLabel} />
                            <EventDetailField label={t('memory.l1.tomDepth')} value={tomDepthLabel} />
                            <EventDetailField label={t('memory.l1.embeddingProfile')} value={event.embedding_profile_id} monospace />
                            <EventDetailField label={t('memory.l1.embeddingChunks')} value={event.embedding_chunk_count ?? null} />
                            <EventDetailField label={t('memory.l1.lastEmbeddedAt')} value={event.last_embedded_at ? formatTimestamp(event.last_embedded_at) : null} />
                            <EventDetailField label={t('memory.l1.importanceScore')} value={importanceScore} />
                            <EventDetailField label={t('memory.l1.cognitionEligible')} value={event.cognition_eligible ? t('memory.l1.yes') : t('memory.l1.no')} />
                            <EventDetailField label={t('memory.l1.authorType')} value={authorTypeLabel} />
                            <EventDetailField label={t('memory.l1.contentType')} value={contentTypeLabel} />
                            <EventDetailField label={t('memory.l1.userId')} value={event.user_id} monospace />
                            <EventDetailField label={t('memory.l1.sessionId')} value={event.session_id} monospace />
                            <EventDetailField label={t('memory.l1.turnId')} value={event.turn_id} monospace />
                            <EventDetailField label={t('memory.l1.taskId')} value={event.task_id} monospace />
                            <EventDetailField label={t('memory.l1.mediaPath')} value={event.media_path} monospace />
                          </div>
                        </details>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default L1Tab;
