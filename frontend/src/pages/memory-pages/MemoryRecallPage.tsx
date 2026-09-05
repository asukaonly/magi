import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { useMemory } from '@/hooks/useMemory';
import type { MemorySearchResultPayload } from '@/api/modules/memory';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';
import { QuickEntrySheet } from '@/components/timeline/manual-entries/QuickEntrySheet';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';

type MemorySearchItem = Record<string, unknown>;

const SEARCH_RESULT_SECTIONS: Array<{
  field: keyof Pick<
    MemorySearchResultPayload,
    | 'l0_workbench'
    | 'l1_events'
    | 'l1_evidence_bundles'
    | 'l1_timeline_summary'
    | 'l2_entity_cards'
    | 'l2_relationships'
    | 'l2_assertions'
    | 'l2_episodes'
    | 'l2_experiences'
    | 'l2_state_facts'
    | 'l2_state_history'
    | 'l3_reflections'
    | 'l4_procedures'
    | 'structured_results'
  >;
  titleKey: string;
}> = [
  { field: 'structured_results', titleKey: 'structured' },
  { field: 'l2_experiences', titleKey: 'experiences' },
  { field: 'l2_episodes', titleKey: 'episodes' },
  { field: 'l2_state_facts', titleKey: 'stateFacts' },
  { field: 'l2_state_history', titleKey: 'stateHistory' },
  { field: 'l2_relationships', titleKey: 'relationships' },
  { field: 'l2_assertions', titleKey: 'assertions' },
  { field: 'l2_entity_cards', titleKey: 'entities' },
  { field: 'l1_events', titleKey: 'events' },
  { field: 'l1_evidence_bundles', titleKey: 'evidenceBundles' },
  { field: 'l1_timeline_summary', titleKey: 'timelineSummary' },
  { field: 'l3_reflections', titleKey: 'summaries' },
  { field: 'l4_procedures', titleKey: 'procedures' },
  { field: 'l0_workbench', titleKey: 'workbench' },
];

const TITLE_FIELDS = [
  'natural_summary',
  'display_title',
  'user_label',
  'title',
  'headline',
  'label',
  'name',
  'summary',
  'evidence_text',
  'content',
  'event_summary',
  'slice_narrative',
  'user_note',
  'skill_name',
  'procedure',
  'predicate',
  'subject',
  'object',
];

const BODY_FIELDS = [
  'natural_summary',
  'evidence_text',
  'content',
  'summary',
  'description',
  'slice_narrative',
  'slice_sensory_detail',
  'standout_reason',
  'text',
  'value',
  'excerpt',
  'snippet',
  'evidence',
  'activity',
  'result',
  'reason',
  'rationale',
  'details',
];

const META_FIELDS = ['source_type', 'source', 'memory_domain', 'status', 'score', 'confidence', 'importance_score'];

export const MemoryRecallPage = () => {
  const { t } = useTranslation('app');
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [entrySheetOpen, setEntrySheetOpen] = useState(false);
  const {
    loading, stats, searchQuery, setSearchQuery, searchResults, searching, handleSearch,
  } = useMemory({ initialLoadScope: 'overview' });

  const resultSections = SEARCH_RESULT_SECTIONS.map((section) => ({
    ...section,
    items: getSearchItems(searchResults[section.field]),
  })).filter((section) => section.items.length > 0);

  const runSearch = () => {
    setHasSearched(true);
    void handleSearch();
  };

  const noResults = resultSections.length === 0;
  const hasLoadedMemoryTotal = typeof stats.stored_records === 'number';
  const memoryTotal = stats.stored_records ?? 0;
  const showColdStartGuide = !loading && hasLoadedMemoryTotal && memoryTotal === 0 && !hasSearched && noResults;
  const showSearching = hasSearched && searching;
  const showNoResults = hasSearched && !searching && noResults;

  return (
    <MemoryPageFrame title={t('memory.recall.title')} description={t('memory.recall.subtitle')} hideHeader>
      {showColdStartGuide && (
        <div className="mb-6 flex flex-col gap-4">
          <p className="text-sm text-[#7d685a] dark:text-[#c8b7a7]">
            {t('memory.recall.emptyStateIntro')}
          </p>
          <EmptyStateAvailableSensors />
          <button
            type="button"
            onClick={() => setEntrySheetOpen(true)}
            className="self-start rounded-full border border-[#d8c9b8] px-4 py-1.5 text-xs text-[#35261f] dark:border-[#7d685a] dark:text-[#f4eadf]"
          >
            {t('memory.recall.manualEntry')}
          </button>
        </div>
      )}
      <section data-testid="memory-recall-search" className="space-y-4">
        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
          <Input
            className={MEMORY_FILTER_INPUT_CLASS}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('memory.recall.searchPlaceholder')}
            onKeyDown={(e) => { if (e.key === 'Enter') runSearch(); }}
          />
          <Button onClick={runSearch} disabled={searching}>
            {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
          </Button>
        </div>

        {showSearching ? (
          <div role="status" className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.recall.searching')}</span>
          </div>
        ) : null}

        {showNoResults ? (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.recall.noResults')}</div>
        ) : null}

        {resultSections.length > 0 ? (
          <div data-testid="memory-recall-results" className="space-y-5">
            {resultSections.map((section) => (
              <section key={section.field} className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                    {t(`memory.recall.sections.${section.titleKey}`)}
                  </h2>
                  <span className="text-xs text-[hsl(var(--memory-muted))]">
                    {t('memory.recall.resultCount', { count: section.items.length })}
                  </span>
                </div>
                <div className="grid gap-2">
                  {section.items.map((item, index) => {
                    const title = getSearchItemTitle(item, getResultFallback(section.field, item, index, t));
                    const body = getSearchItemBody(item, title);
                    const meta = getSearchItemMeta(item);
                    return (
                      <article
                        key={`${section.field}-${getSearchItemKey(item, index)}`}
                        className="rounded-lg border border-[hsl(var(--memory-border)/0.46)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3"
                      >
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0 space-y-1">
                            <h3 className="break-words text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">
                              {title}
                            </h3>
                            {body ? (
                              <p className="break-words text-sm leading-6 text-[hsl(var(--memory-body))]">
                                {body}
                              </p>
                            ) : null}
                          </div>
                          {meta.length > 0 ? (
                            <div className="flex flex-wrap gap-1 sm:justify-end">
                              {meta.map((value) => (
                                <span
                                  key={value}
                                  className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.72)] px-2 py-1 text-xs text-[hsl(var(--memory-muted))]"
                                >
                                  {value}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        ) : null}

        <button
          type="button"
          className="text-xs text-[hsl(var(--memory-muted))] underline-offset-2 hover:underline"
          onClick={() => setShowDiagnostics((v) => !v)}
        >
          {t('memory.recall.advancedToggle')}
        </button>
        {showDiagnostics ? (
          <div data-testid="memory-recall-diagnostics" className="rounded-xl border border-[hsl(var(--memory-border)/0.46)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3 text-xs text-[hsl(var(--memory-muted))]">
            <pre>{JSON.stringify(searchResults.trace ?? {}, null, 2)}</pre>
          </div>
        ) : null}
      </section>
      <QuickEntrySheet
        open={entrySheetOpen}
        onClose={() => setEntrySheetOpen(false)}
        onSaved={() => setEntrySheetOpen(false)}
      />
    </MemoryPageFrame>
  );
};

export default MemoryRecallPage;

const getSearchItems = (value: unknown): MemorySearchItem[] => (
  Array.isArray(value) ? value.filter(isRecord) : []
);

const isRecord = (value: unknown): value is MemorySearchItem => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const getSearchItemKey = (item: MemorySearchItem, index: number): string => {
  const key = pickReadableValue(item, ['id', 'event_id', 'summary_id', 'episode_id', 'experience_id', 'skill_id']);
  return key || String(index);
};

const getResultFallback = (
  field: string,
  item: MemorySearchItem,
  index: number,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const sourceEventCount = item.source_event_count;
  if ((field === 'l2_episodes' || field === 'l2_experiences') && typeof sourceEventCount === 'number') {
    return t('memory.recall.episodeFallback', { count: sourceEventCount });
  }
  const observationCount = item.observation_count;
  if (typeof observationCount === 'number' && observationCount > 0) {
    return t('memory.recall.observationFallback', { count: observationCount });
  }
  return t('memory.recall.resultFallback', { index: index + 1 });
};

const getSearchItemTitle = (item: MemorySearchItem, fallback: string): string => (
  pickReadableValue(item, TITLE_FIELDS) || fallback
);

const getSearchItemBody = (item: MemorySearchItem, title: string): string | null => {
  return pickReadableValue(item, BODY_FIELDS, new Set([title]));
};

const getSearchItemMeta = (item: MemorySearchItem): string[] => {
  const values: string[] = [];
  for (const field of META_FIELDS) {
    const value = item[field];
    const formatted = field.includes('score') || field === 'confidence'
      ? formatScore(value)
      : formatMemoryValue(value);
    if (formatted && !values.includes(formatted)) {
      values.push(formatted);
    }
  }
  return values.slice(0, 3);
};

const pickReadableValue = (
  item: MemorySearchItem,
  fields: string[],
  exclude: Set<string> = new Set()
): string | null => {
  for (const field of fields) {
    const formatted = formatMemoryValue(item[field]);
    if (formatted && !exclude.has(formatted)) {
      return formatted;
    }
  }
  return null;
};

const formatMemoryValue = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (
      !normalized
      || normalized === 'no signals'
      || normalized.includes('first_entity[')
      || normalized.includes('duration[')
      || /^[a-z_]+:[0-9a-f]{8,}/i.test(normalized)
    ) {
      return null;
    }
    return normalized || null;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => formatMemoryValue(item))
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.slice(0, 4).join(' · ') : null;
  }
  if (isRecord(value)) {
    return pickReadableValue(value, [...TITLE_FIELDS, ...BODY_FIELDS])
      || Object.entries(value)
        .map(([, nestedValue]) => formatMemoryValue(nestedValue))
        .filter((item): item is string => Boolean(item))
        .slice(0, 3)
        .join(' · ')
      || null;
  }
  return null;
};

const formatScore = (value: unknown): string | null => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return formatMemoryValue(value);
  }
  return value >= 0 && value <= 1 ? value.toFixed(2) : String(value);
};
