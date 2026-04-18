import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowRight, CheckCircle2, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
} from './MemoryPageFrame';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

export const MemoryOverviewPage = () => {
  const { t } = useTranslation('app');
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

  const searchSections = [
    {
      key: 'events',
      label: t('memory.nav.events'),
      path: '/memory/events',
      count: searchResults.l1_events.length,
      items: searchResults.l1_events,
    },
    {
      key: 'knowledge',
      label: t('memory.nav.knowledge'),
      path: '/memory/knowledge',
      count: searchResults.l2_entity_cards.length + searchResults.l2_relationships.length,
      items: [...searchResults.l2_entity_cards, ...searchResults.l2_relationships],
    },
    {
      key: 'reflection',
      label: t('memory.nav.reflection'),
      path: '/memory/reflection',
      count: searchResults.l3_reflections.length,
      items: searchResults.l3_reflections,
    },
    {
      key: 'skills',
      label: t('memory.nav.skills'),
      path: '/memory/skills',
      count: searchResults.l4_procedures.length,
      items: searchResults.l4_procedures,
    },
  ];

  const totalSearchHits = searchSections.reduce((sum, section) => sum + section.count, 0);
  const hasSearched = searchQuery.trim().length > 0;

  const totalMemories = stats.total_memories
    ?? (stats.l1.event_count + stats.l2.relation_count + stats.l2.assertion_count
        + stats.l3.summary_count + stats.l4.skill_count);
  const diskUsage = stats.disk_usage_bytes ?? 0;
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
                total: totalMemories.toLocaleString(),
                size: formatBytes(diskUsage),
              })
            : t('memory.overview.storageSummaryCompact', {
                total: totalMemories.toLocaleString(),
              })
          : t('memory.overview.subtitle')
      }
      actions={
        <Button
          variant="outline"
          className="h-9 rounded-xl border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-4 text-sm text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle)/0.82)]"
          onClick={() => void refreshAll()}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
    >
      {/* Search */}
      <section data-testid="memory-overview-search" className="space-y-4">
        <div className="flex gap-2">
          <Input
            id="memory-overview-search"
            className={`flex-1 ${MEMORY_FILTER_INPUT_CLASS}`}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t('memory.searchPlaceholder')}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void handleSearch();
            }}
          />
          <Button
            className="h-9 shrink-0 rounded-xl px-5"
            onClick={() => void handleSearch()}
            disabled={searching}
          >
            {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
            <span className="ml-2">{t('memory.search')}</span>
          </Button>
        </div>

        {/* Search results grouped by layer */}
        {hasSearched && (
          <div data-testid="memory-overview-search-results" className="space-y-3">
            {totalSearchHits > 0 ? (
              searchSections
                .filter((section) => section.count > 0)
                .map((section) => (
                  <div key={section.key} className={MEMORY_SECTION_CARD_CLASS}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                        {section.label}
                        <span className="ml-2 text-xs font-normal text-[hsl(var(--memory-muted))]">
                          {t('memory.overview.matchCount', { count: section.count })}
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
                    <div className="mt-2 space-y-1.5">
                      {section.items.slice(0, 3).map((item, idx) => (
                        <div
                          key={idx}
                          className="truncate text-sm leading-6 text-[hsl(var(--memory-body))]"
                        >
                          {describeSearchItem(item)}
                        </div>
                      ))}
                    </div>
                  </div>
                ))
            ) : (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                {t('memory.overview.noSearchResults')}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Attention section */}
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

const describeSearchItem = (item: Record<string, unknown> | undefined): string => {
  if (!item) return '';

  const previewKeys = [
    'canonical_name',
    'source_item_id',
    'content',
    'skill_name',
    'summary',
    'title',
    'entity_id',
    'event_id',
  ];

  for (const key of previewKeys) {
    const value = item[key];
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }

  return JSON.stringify(item);
};

export default MemoryOverviewPage;
