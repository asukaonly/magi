import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  HardDrive,
  Layers,
  Search,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { useMemory } from '@/hooks/useMemory';
import type { MemorySearchQueryMode } from '@/api/modules/memory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';

const SEARCH_SECTION_PREVIEW_LIMIT = 5;
const CURATED_EVIDENCE_LIMIT = 6;

type MemoryWorkbenchSearchMode = 'auto' | 'events' | 'knowledge' | 'summaries' | 'skills' | 'state' | 'episodes';

const SEARCH_MODES: MemoryWorkbenchSearchMode[] = [
  'auto',
  'events',
  'knowledge',
  'summaries',
  'skills',
  'state',
  'episodes',
];

const SEARCH_MODE_QUERY_MODE: Record<MemoryWorkbenchSearchMode, MemorySearchQueryMode | undefined> = {
  auto: undefined,
  events: 'event_stream',
  knowledge: 'exact_fact',
  summaries: 'summary',
  skills: 'strategy',
  state: 'current_state',
  episodes: 'episode_recall',
};

const SEARCH_MODE_ICONS: Record<MemoryWorkbenchSearchMode, LucideIcon> = {
  auto: Sparkles,
  events: Database,
  knowledge: Brain,
  summaries: FileText,
  skills: Wrench,
  state: Layers,
  episodes: Clock,
};

type SearchResultKind =
  | 'event'
  | 'entity'
  | 'relationship'
  | 'assertion'
  | 'episode'
  | 'stateFact'
  | 'stateHistory'
  | 'reflection'
  | 'skill';

type SearchResultEntry = {
  kind: SearchResultKind;
  item: Record<string, unknown>;
};

type SearchResultPreview = {
  title: string;
  body: string | null;
  meta: string[];
  kindLabel: string;
};

type Translate = (key: string, options?: Record<string, unknown>) => string;

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, unitIndex);
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unitIndex]}`;
}

const MemoryOverviewMetric = ({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) => (
  <div className="flex min-w-[116px] items-center gap-2 rounded-sm bg-[hsl(var(--memory-panel-subtle)/0.68)] px-3 py-2">
    <span className="flex h-7 w-7 items-center justify-center rounded-sm bg-[hsl(var(--memory-accent-soft)/0.72)] text-[hsl(var(--memory-accent))]">
      {icon}
    </span>
    <span className="min-w-0">
      <span className="block text-xs leading-4 text-[hsl(var(--memory-muted))]">{label}</span>
      <span className="block truncate text-sm font-semibold leading-5 text-[hsl(var(--memory-title))]">{value}</span>
    </span>
  </div>
);

export const MemoryOverviewPage = () => {
  const { t } = useTranslation('app');
  const [searchMode, setSearchMode] = useState<MemoryWorkbenchSearchMode>('auto');
  const {
    loading,
    stats,
    searchQuery,
    setSearchQuery,
    searchResults,
    searching,
    handleSearch,
    refreshAll,
  } = useMemory({ initialLoadScope: 'overview' });

  const selectedQueryMode = SEARCH_MODE_QUERY_MODE[searchMode];
  const runSearch = () => void handleSearch(selectedQueryMode);

  const eventItems = toSearchEntries(searchResults.l1_events, 'event');
  const knowledgeItems = [
    ...toSearchEntries(searchResults.l2_entity_cards, 'entity'),
    ...toSearchEntries(searchResults.l2_relationships, 'relationship'),
    ...toSearchEntries(searchResults.l2_assertions ?? [], 'assertion'),
    ...toSearchEntries(searchResults.l2_episodes ?? [], 'episode'),
    ...toSearchEntries(searchResults.l2_state_facts ?? [], 'stateFact'),
    ...toSearchEntries(searchResults.l2_state_history ?? [], 'stateHistory'),
  ];
  const reflectionItems = toSearchEntries(searchResults.l3_reflections, 'reflection');
  const skillItems = toSearchEntries(searchResults.l4_procedures, 'skill');

  const searchSections = [
    {
      key: 'events',
      layer: 'L1',
      label: t('memory.nav.events'),
      path: '/memory/events',
      count: eventItems.length,
      items: eventItems,
    },
    {
      key: 'knowledge',
      layer: 'L2',
      label: t('memory.nav.knowledge'),
      path: '/memory/knowledge',
      count: knowledgeItems.length,
      items: knowledgeItems,
    },
    {
      key: 'reflection',
      layer: 'L3',
      label: t('memory.nav.reflection'),
      path: '/memory/reflection',
      count: reflectionItems.length,
      items: reflectionItems,
    },
    {
      key: 'skills',
      layer: 'L4',
      label: t('memory.nav.skills'),
      path: '/memory/skills',
      count: skillItems.length,
      items: skillItems,
    },
  ];

  const totalSearchHits = searchSections.reduce((sum, section) => sum + section.count, 0);
  const hasSearched = searchQuery.trim().length > 0;
  const curatedEvidence = rankSearchEntries([
    ...eventItems,
    ...knowledgeItems,
    ...reflectionItems,
    ...skillItems,
  ]).slice(0, CURATED_EVIDENCE_LIMIT);
  const trace = searchResults.trace ?? {};
  const traceLayerCounts = getTraceRecord(trace, 'layer_result_counts');
  const layerCounts = searchSections.map((section) => ({
    ...section,
    count: getTraceLayerCount(traceLayerCounts, section.layer) ?? section.count,
  }));
  const resolvedQueryMode = getTraceString(trace, 'resolved_query_mode')
    ?? getTraceString(trace, 'query_mode')
    ?? selectedQueryMode
    ?? 'auto';
  const requestedQueryMode = getTraceString(trace, 'requested_query_mode')
    ?? selectedQueryMode
    ?? 'auto';
  const executedLayers = getTraceStringList(trace, 'executed_layers');

  const totalMemories = stats.total_memories
    ?? (stats.l1.event_count + stats.l2.relation_count + stats.l2.assertion_count
        + stats.l3.summary_count + stats.l4.skill_count);
  const diskUsage = stats.disk_usage_bytes ?? 0;
  const formattedTotalMemories = totalMemories.toLocaleString();
  const formattedDiskUsage = formatBytes(diskUsage);
  const pendingAssertions = stats.attention?.pending_assertions ?? 0;
  const openBreakers = stats.attention?.open_circuit_breakers ?? stats.l4.open_circuit_breakers ?? 0;
  const attentionTotal = pendingAssertions + openBreakers;

  return (
    <MemoryPageFrame
      title={t('memory.nav.overview')}
      description={
        totalMemories > 0
          ? diskUsage > 0
            ? t('memory.overview.storageSummary', {
                total: formattedTotalMemories,
                size: formattedDiskUsage,
              })
            : t('memory.overview.storageSummaryCompact', {
                total: formattedTotalMemories,
              })
          : t('memory.overview.subtitle')
      }
      actions={
        <>
          <div data-testid="memory-overview-stats" className="flex flex-wrap items-center gap-2">
            <MemoryOverviewMetric
              icon={<Database className="h-4 w-4" />}
              label={t('memory.overview.totalMemoriesLabel')}
              value={formattedTotalMemories}
            />
            <MemoryOverviewMetric
              icon={<HardDrive className="h-4 w-4" />}
              label={t('memory.overview.diskUsageLabel')}
              value={formattedDiskUsage}
            />
          </div>
          <Button
            variant="outline"
            className="h-9 rounded-xl border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-4 text-sm text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle)/0.82)]"
            onClick={() => void refreshAll()}
            disabled={loading}
          >
            {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
            {t('memory.refresh')}
          </Button>
        </>
      }
    >
      <section data-testid="memory-overview-search" className="space-y-4">
        <div className="flex gap-2">
          <Input
            id="memory-overview-search"
            className={`flex-1 ${MEMORY_FILTER_INPUT_CLASS}`}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t('memory.searchPlaceholder')}
            onKeyDown={(event) => {
              if (event.key === 'Enter') runSearch();
            }}
          />
          <Button
            className="h-9 shrink-0 rounded-xl px-5"
            onClick={runSearch}
            disabled={searching}
          >
            {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
            <span className="ml-2">{t('memory.search')}</span>
          </Button>
        </div>

        <div data-testid="memory-overview-search-modes" className="flex flex-wrap gap-2">
          {SEARCH_MODES.map((mode) => {
            const Icon = SEARCH_MODE_ICONS[mode];
            const selected = searchMode === mode;
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={selected}
                title={t(`memory.overview.searchModes.${mode}.description`)}
                className={`flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors ${selected
                  ? 'border-[hsl(var(--memory-accent)/0.62)] bg-[hsl(var(--memory-accent-soft)/0.72)] text-[hsl(var(--memory-accent))]'
                  : 'border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.48)] text-[hsl(var(--memory-body))] hover:border-[hsl(var(--memory-accent)/0.38)] hover:bg-[hsl(var(--memory-panel-subtle)/0.68)]'
                }`}
                onClick={() => setSearchMode(mode)}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{t(`memory.overview.searchModes.${mode}.label`)}</span>
              </button>
            );
          })}
        </div>

        {hasSearched && (
          <div data-testid="memory-overview-search-results" className="space-y-3">
            {totalSearchHits > 0 ? (
              <>
                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                        {t('memory.overview.searchOverviewTitle')}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                        {t('memory.overview.searchOverviewBody', {
                          total: totalSearchHits,
                          query: searchQuery.trim(),
                          mode: t(`memory.overview.searchModes.${searchMode}.label`),
                        })}
                      </div>
                    </div>
                    <span className="rounded-sm bg-[hsl(var(--memory-accent-soft)/0.72)] px-2 py-1 text-xs font-medium text-[hsl(var(--memory-accent))]">
                      {t('memory.overview.modeBadge', {
                        mode: t(`memory.overview.searchModes.${searchMode}.label`),
                      })}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {layerCounts.map((section) => (
                      <span
                        key={section.key}
                        className="rounded-sm border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]"
                      >
                        {section.layer} · {section.label}: {section.count}
                      </span>
                    ))}
                  </div>
                </div>

                {curatedEvidence.length > 0 ? (
                  <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)] p-4">
                    <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                      {t('memory.overview.curatedEvidenceTitle')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                      {t('memory.overview.curatedEvidenceBody')}
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {curatedEvidence.map((entry, index) => (
                        <SearchResultPreviewCard
                          key={getSearchResultKey(entry, index)}
                          entry={entry}
                          t={t}
                        />
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)] p-4">
                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                    {t('memory.overview.layeredResultsTitle')}
                  </div>
                  <div className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                    {t('memory.overview.searchResultSummary', { total: totalSearchHits })}
                  </div>
                  <div className="mt-3 space-y-3">
                    {searchSections
                      .filter((section) => section.count > 0)
                      .map((section) => {
                        const visibleItems = section.items.slice(0, SEARCH_SECTION_PREVIEW_LIMIT);
                        return (
                          <div
                            key={section.key}
                            className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.42)] p-3"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                                {section.label}
                                <span className="ml-2 text-xs font-normal text-[hsl(var(--memory-muted))]">
                                  {t('memory.overview.resultCountLabel', {
                                    shown: visibleItems.length,
                                    total: section.count,
                                  })}
                                </span>
                              </div>
                              <Link
                                to={section.path}
                                className="flex items-center gap-1 text-xs text-[hsl(var(--memory-accent))] hover:underline"
                              >
                                {t('memory.overview.viewAll')}
                                <ArrowRight className="h-3 w-3" />
                              </Link>
                            </div>
                            <div className="mt-3 space-y-2">
                              {visibleItems.map((entry, index) => (
                                <SearchResultPreviewCard
                                  key={getSearchResultKey(entry, index)}
                                  entry={entry}
                                  t={t}
                                />
                              ))}
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </div>

                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.46)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3">
                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                    {t('memory.overview.diagnosticsTitle')}
                  </div>
                  <div className="mt-2 grid gap-2 text-xs text-[hsl(var(--memory-muted))] md:grid-cols-3">
                    <span>{t('memory.overview.requestedModeLabel', { mode: formatQueryMode(requestedQueryMode, t) })}</span>
                    <span>{t('memory.overview.resolvedModeLabel', { mode: formatQueryMode(resolvedQueryMode, t) })}</span>
                    <span>
                      {t('memory.overview.executedLayersLabel', {
                        layers: executedLayers.length > 0 ? executedLayers.join(', ') : t('memory.overview.noneValue'),
                      })}
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                {t('memory.overview.noSearchResults')}
              </div>
            )}
          </div>
        )}
      </section>

      <section data-testid="memory-overview-attention" className="mt-5">
        {attentionTotal > 0 ? (
          <div className="rounded-2xl border border-[hsl(var(--memory-accent)/0.35)] bg-[hsl(var(--memory-accent-soft)/0.4)] px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
              <AlertTriangle className="h-4 w-4 text-[hsl(var(--memory-accent))]" />
              {t('memory.overview.attentionTitle', { count: attentionTotal })}
            </div>
            <div className="mt-3 space-y-2">
              {pendingAssertions > 0 && (
                <Link
                  to="/memory/knowledge"
                  className="group flex items-center justify-between rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.78)] px-4 py-2.5 transition-colors hover:border-[hsl(var(--memory-accent)/0.4)]"
                >
                  <span className="text-sm text-[hsl(var(--memory-body))]">
                    {t('memory.overview.pendingAssertions', { count: pendingAssertions })}
                  </span>
                  <ArrowRight className="h-4 w-4 text-[hsl(var(--memory-accent))] transition-transform group-hover:translate-x-0.5" />
                </Link>
              )}
              {openBreakers > 0 && (
                <Link
                  to="/memory/skills"
                  className="group flex items-center justify-between rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.78)] px-4 py-2.5 transition-colors hover:border-[hsl(var(--memory-accent)/0.4)]"
                >
                  <span className="text-sm text-[hsl(var(--memory-body))]">
                    {t('memory.overview.openBreakers', { count: openBreakers })}
                  </span>
                  <ArrowRight className="h-4 w-4 text-[hsl(var(--memory-accent))] transition-transform group-hover:translate-x-0.5" />
                </Link>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-2xl border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-5 py-4 text-sm text-[hsl(var(--memory-body))]">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            {t('memory.overview.allClear')}
          </div>
        )}
      </section>
    </MemoryPageFrame>
  );
};

const toSearchEntries = (
  items: Array<Record<string, unknown>> | undefined,
  kind: SearchResultKind
): SearchResultEntry[] => (items ?? []).filter(isRecord).map((item) => ({ kind, item }));

const SearchResultPreviewCard = ({
  entry,
  t,
}: {
  entry: SearchResultEntry;
  t: Translate;
}) => {
  const preview = buildSearchResultPreview(entry, t);
  return (
    <div className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.46)] px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 rounded-sm bg-[hsl(var(--memory-accent-soft)/0.7)] px-2 py-0.5 text-[0.68rem] font-medium text-[hsl(var(--memory-accent))]">
          {preview.kindLabel}
        </span>
        <div className="min-w-0 truncate text-sm font-medium leading-5 text-[hsl(var(--memory-title))]">
          {preview.title}
        </div>
      </div>
      {preview.body ? (
        <div className="mt-1 max-h-10 overflow-hidden text-sm leading-5 text-[hsl(var(--memory-body))]">
          {preview.body}
        </div>
      ) : null}
      {preview.meta.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
          {preview.meta.map((part) => (
            <span key={part}>{part}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
};

const rankSearchEntries = (entries: SearchResultEntry[]): SearchResultEntry[] => (
  [...entries].sort((left, right) => {
    const scoreDiff = getEntryScore(right) - getEntryScore(left);
    if (scoreDiff !== 0) return scoreDiff;
    return getTimestampMilliseconds(right.item) - getTimestampMilliseconds(left.item);
  })
);

const getEntryScore = (entry: SearchResultEntry): number => (
  readNumber(entry.item, ['retrieval_score', 'score']) ?? 0
);

const getTraceRecord = (trace: Record<string, unknown>, key: string): Record<string, unknown> | null => {
  const value = trace[key];
  return isRecord(value) ? value : null;
};

const getTraceString = (trace: Record<string, unknown>, key: string): string | null => {
  const value = trace[key];
  return typeof value === 'string' && value.trim() ? value : null;
};

const getTraceStringList = (trace: Record<string, unknown>, key: string): string[] => {
  const value = trace[key];
  if (!Array.isArray(value)) return [];
  return value.map((part) => (typeof part === 'string' ? part.trim() : '')).filter(Boolean);
};

const getTraceLayerCount = (counts: Record<string, unknown> | null, layer: string): number | null => {
  const value = counts?.[layer];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const formatQueryMode = (mode: string, t: Translate): string => {
  if (mode === 'auto') return t('memory.overview.searchModes.auto.label');
  const label = t(`memory.overview.queryModes.${mode}`);
  return label === `memory.overview.queryModes.${mode}` ? mode : label;
};

const buildSearchResultPreview = (entry: SearchResultEntry, t: Translate): SearchResultPreview => {
  const title = truncateText(getReadableTitle(entry.item, entry.kind) || t('memory.overview.untitledResult'), 120);
  const body = getReadableBody(entry.item, title);
  const kindLabel = t(`memory.overview.resultKinds.${entry.kind}`);
  return {
    title,
    body: body ? truncateText(body, 220) : null,
    kindLabel,
    meta: buildSearchResultMeta(entry.item, t),
  };
};

const getReadableTitle = (item: Record<string, unknown>, kind: SearchResultKind): string | null => {
  const metadata = getMetadata(item);
  const musicTitle = getMusicTitle(metadata ?? item);
  if (musicTitle) return musicTitle;

  if (kind === 'relationship') {
    const subject = readDeepString(item, ['subject', 'subject_entity_id', 'source_entity_id', 'from_entity_id']);
    const predicate = readDeepString(item, ['predicate', 'relation_type', 'relationship_type']);
    const object = readDeepString(item, ['object', 'object_entity_id', 'target_entity_id', 'to_entity_id']);
    const relationTitle = [subject, predicate, object].filter(Boolean).join(' ');
    if (relationTitle) return relationTitle;
  }

  if (kind === 'assertion') {
    const entity = readDeepString(item, ['entity_id', 'subject_id']);
    const trait = readDeepString(item, ['trait_name', 'predicate', 'attribute']);
    const value = readDeepString(item, ['value', 'trait_value', 'object']);
    const assertionTitle = [entity, trait, value].filter(Boolean).join(' · ');
    if (assertionTitle) return assertionTitle;
  }

  return readDeepString(item, [
    'canonical_name',
    'display_title',
    'title',
    'name',
    'skill_name',
    'summary',
    'content',
    'text',
    'description',
  ]);
};

const getReadableBody = (item: Record<string, unknown>, title: string): string | null => {
  const metadata = getMetadata(item);
  const body = readDeepString(item, [
    'content',
    'summary',
    'description',
    'evidence',
    'rationale',
    'reason',
    'value',
    'trait_value',
  ]) ?? readDeepString(metadata ?? {}, [
    'description',
    'album_name',
    'artist_name',
    'source_app',
    'url',
  ]);

  if (!body || body === title) return null;
  return body;
};

const buildSearchResultMeta = (
  item: Record<string, unknown>,
  t: Translate
): string[] => {
  const source = readDeepString(item, ['source', 'source_type']);
  const domain = readDeepString(item, ['memory_domain', 'domain']);
  const timestamp = readTimestamp(item);
  const score = readNumber(item, ['retrieval_score', 'score']);
  const meta: string[] = [];

  if (source) meta.push(t('memory.overview.sourceMeta', { value: source }));
  if (domain) meta.push(t('memory.overview.domainMeta', { value: domain }));
  if (timestamp) meta.push(t('memory.overview.timeMeta', { value: timestamp }));
  if (typeof score === 'number') meta.push(t('memory.overview.scoreMeta', { value: score.toFixed(2) }));

  return Array.from(new Set(meta));
};

const getSearchResultKey = (entry: SearchResultEntry, index: number): string => {
  const id = readDeepString(entry.item, [
    'event_id',
    'entity_id',
    'relationship_id',
    'assertion_id',
    'episode_id',
    'summary_id',
    'skill_id',
    'id',
  ]);
  return `${entry.kind}:${id ?? index}`;
};

const getMetadata = (item: Record<string, unknown>): Record<string, unknown> | null => {
  const metadata = item.metadata_json ?? item.metadata;
  return isRecord(metadata) ? metadata : null;
};

const getMusicTitle = (item: Record<string, unknown> | null): string | null => {
  if (!item) return null;
  const track = readDeepString(item, ['track_name', 'song_name', 'music_title', 'title', 'name']);
  const artist = readDeepString(item, ['artist_name', 'artist', 'artists']);
  if (track && artist) return `${track} - ${artist}`;
  return track;
};

const readDeepString = (item: Record<string, unknown>, keys: string[]): string | null => {
  for (const key of keys) {
    const value = normalizeText(item[key]);
    if (value) return value;
  }

  for (const value of Object.values(item)) {
    if (isRecord(value)) {
      const nested = readDeepString(value, keys);
      if (nested) return nested;
    }
  }

  return null;
};

const normalizeText = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(normalizeText).filter(Boolean);
    return parts.length > 0 ? parts.join(', ') : null;
  }
  return null;
};

const readNumber = (item: Record<string, unknown>, keys: string[]): number | null => {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
};

const readTimestamp = (item: Record<string, unknown>): string | null => {
  const value = readNumber(item, ['timestamp', 'created_at', 'updated_at', 'period_start']);
  if (value === null || value <= 0) return null;
  const milliseconds = value > 10_000_000_000 ? value : value * 1000;
  return new Date(milliseconds).toLocaleString();
};

const getTimestampMilliseconds = (item: Record<string, unknown>): number => {
  const value = readNumber(item, ['timestamp', 'created_at', 'updated_at', 'period_start']);
  if (value === null || value <= 0) return 0;
  return value > 10_000_000_000 ? value : value * 1000;
};

const truncateText = (value: string, maxLength: number): string => (
  value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value
);

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

export default MemoryOverviewPage;
