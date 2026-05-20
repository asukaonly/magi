import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { useMemory } from '@/hooks/useMemory';
import type { MemorySearchQueryMode } from '@/api/modules/memory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';

type RecallMode = 'auto' | 'events' | 'knowledge' | 'summaries' | 'skills' | 'state' | 'episodes';

const MODE_TO_QUERY: Record<RecallMode, MemorySearchQueryMode | undefined> = {
  auto: undefined,
  events: 'event_stream',
  knowledge: 'exact_fact',
  summaries: 'summary',
  skills: 'strategy',
  state: 'current_state',
  episodes: 'episode_recall',
};

const RECALL_MODES: RecallMode[] = ['auto', 'events', 'knowledge', 'summaries', 'skills', 'state', 'episodes'];

export const MemoryRecallPage = () => {
  const { t } = useTranslation('app');
  const [mode, setMode] = useState<RecallMode>('auto');
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const {
    searchQuery, setSearchQuery, searchResults, searching, handleSearch,
  } = useMemory({ initialLoadScope: 'overview' });

  const runSearch = () => {
    const queryMode = MODE_TO_QUERY[mode];
    void handleSearch(queryMode);
  };

  const modeOptions = RECALL_MODES.map((m) => ({
    value: m,
    label: t(`memory.recall.modes.${m}`),
  }));

  const noResults =
    (searchResults.l1_events?.length ?? 0) === 0
    && (searchResults.l2_relationships?.length ?? 0) === 0
    && (searchResults.l3_reflections?.length ?? 0) === 0
    && (searchResults.l4_procedures?.length ?? 0) === 0;

  return (
    <MemoryPageFrame title={t('memory.recall.title')} description={t('memory.recall.subtitle')}>
      <section data-testid="memory-recall-search" className="space-y-4">
        <div className="grid gap-2 md:grid-cols-[168px_minmax(0,1fr)_auto]">
          <SelectField
            ariaLabel={t('memory.recall.title')}
            value={mode}
            onChange={(v) => setMode((v || 'auto') as RecallMode)}
            options={modeOptions}
            allowEmpty={false}
            triggerClassName={`${MEMORY_FILTER_SELECT_CLASS} justify-between shadow-none`}
            menuClassName="rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] shadow-[0_10px_20px_rgba(15,23,42,0.06)]"
          />
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

        {noResults ? (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.recall.noResults')}</div>
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
    </MemoryPageFrame>
  );
};

export default MemoryRecallPage;
