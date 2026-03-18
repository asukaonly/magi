import { useTranslation } from 'react-i18next';
import { ArrowRight, Search, Sparkles, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { ClearMemoryDialog } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MemoryHeroStat,
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

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
    clearDialogOpen,
    setClearDialogOpen,
    clearConfirmText,
    setClearConfirmText,
    clearing,
    handleClearRequest,
    handleClearConfirm,
  } = useMemory();

  const overviewLinks = [
    { label: t('memory.nav.workbench'), path: '/memory/workbench', stat: stats.l0.active_sessions },
    { label: t('memory.nav.events'), path: '/memory/events', stat: stats.l1.event_count },
    { label: t('memory.nav.knowledge'), path: '/memory/knowledge', stat: stats.l2.relation_count },
    { label: t('memory.nav.reflection'), path: '/memory/reflection', stat: stats.l3.summary_count },
    { label: t('memory.nav.skills'), path: '/memory/skills', stat: stats.l4.skill_count },
  ];

  const recentChanges = [
    { title: t('memory.overview.changes.summaryTitle'), value: stats.l3.summary_count },
    { title: t('memory.overview.changes.relationTitle'), value: stats.l2.relation_count },
    { title: t('memory.overview.changes.skillTitle'), value: stats.l4.skill_count },
  ];

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
  const recommendedLayers = searchSections
    .filter((section) => section.count > 0)
    .sort((left, right) => right.count - left.count)
    .slice(0, 3);

  return (
    <>
      <MemoryPageFrame
        title={t('memory.nav.overview')}
        description={t('memory.overview.subtitle')}
        eyebrow={t('memory.overview.eyebrow')}
        heroStats={(
          <div
            data-testid="memory-overview-signal-strip"
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
          >
            <MemoryHeroStat label={t('memory.l0.activeSessions')} value={stats.l0.active_sessions} tone="accent" />
            <MemoryHeroStat label={t('memory.l1.totalEvents')} value={stats.l1.event_count} />
            <MemoryHeroStat label={t('memory.l2.relationCount')} value={stats.l2.relation_count} />
            <MemoryHeroStat label={t('memory.l4.skillCount')} value={stats.l4.skill_count} />
          </div>
        )}
        heroAside={(
          <div className="space-y-3">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
              {t('memory.overview.asideLabel')}
            </div>
            <div className="text-lg font-semibold text-[#35261c]">{t('memory.overview.asideTitle')}</div>
            <p className="leading-6">{t('memory.overview.asideBody')}</p>
          </div>
        )}
        actions={(
          <>
            <Button
              variant="outline"
              className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
              onClick={() => void refreshAll()}
              disabled={loading}
            >
              {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
              {t('memory.refresh')}
            </Button>
            <Button className="rounded-2xl" variant="destructive" onClick={handleClearRequest}>
              <Trash2 className="mr-2 h-4 w-4" />
              {t('memory.clear')}
            </Button>
          </>
        )}
        filters={(
          <div className="flex flex-col gap-3 lg:flex-row">
            <div className="flex-1 space-y-1.5">
              <label className="text-sm font-medium text-foreground" htmlFor="memory-overview-search">
                {t('memory.overview.searchLabel')}
              </label>
              <div className="flex gap-2">
                <Input
                  id="memory-overview-search"
                  className={MEMORY_FILTER_INPUT_CLASS}
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('memory.searchPlaceholder')}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      void handleSearch();
                    }
                  }}
                />
                <Button className="h-11 rounded-2xl px-5" onClick={() => void handleSearch()} disabled={searching}>
                  {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
                  <span className="ml-2">{t('memory.search')}</span>
                </Button>
              </div>
            </div>
          </div>
        )}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <OverviewMetric label={t('memory.l0.totalGoals')} value={stats.l0.total_goals} />
          <OverviewMetric label={t('memory.l0.totalEntities')} value={stats.l0.total_entities} />
          <OverviewMetric label={t('memory.l2.assertionCount')} value={stats.l2.assertion_count} />
          <OverviewMetric label={t('memory.l3.summaryCount')} value={stats.l3.summary_count} />
          <OverviewMetric label={t('memory.l4.skillCount')} value={stats.l4.skill_count} />
        </div>

        <div className="mt-6 grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
          <MemoryWorkspacePanel
            testId="memory-overview-search-results"
            title={t('memory.overview.searchResultsTitle')}
            description={
              searchQuery.trim().length > 0
                ? t('memory.overview.searchResultsBody', { query: searchQuery })
                : t('memory.overview.searchIdleBody')
            }
          >
            {totalSearchHits > 0 ? (
              <div className="space-y-3">
                {searchSections
                  .filter((section) => section.count > 0)
                  .map((section) => (
                    <div
                      key={section.key}
                      className="rounded-[1.35rem] border border-[#eadccf] bg-white/86 p-4"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-2">
                          <div className="text-sm font-semibold text-[#35261c]">{section.label}</div>
                          <div className="text-sm leading-6 text-[#735c4c]">
                            {describeSearchItem(section.items[0])}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-semibold text-[#7e604b]">{section.count}</div>
                          <div className="text-[11px] uppercase tracking-[0.16em] text-[#9a7f6c]">
                            {t('memory.overview.matchesLabel')}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="rounded-[1.45rem] border border-dashed border-[#dcc7b5] bg-[rgba(247,239,231,0.82)] p-5 text-sm leading-6 text-[#785f4e]">
                {searchQuery.trim().length > 0
                  ? t('memory.overview.noSearchResults')
                  : t('memory.overview.searchIdleHint')}
              </div>
            )}
          </MemoryWorkspacePanel>

          <MemoryWorkspacePanel
            testId="memory-overview-recommended-layers"
            title={t('memory.overview.recommendedTitle')}
            description={t('memory.overview.recommendedBody')}
          >
            {recommendedLayers.length > 0 ? (
              <div className="space-y-3">
                {recommendedLayers.map((section) => (
                  <Link
                    key={section.key}
                    to={section.path}
                    className="group flex items-center justify-between rounded-[1.35rem] border border-[#e9d8cb] bg-white/88 px-4 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-[#d8bea9]"
                  >
                    <div className="space-y-1">
                      <div className="text-sm font-semibold text-[#38281e]">{section.label}</div>
                      <div className="text-xs text-[#8b7260]">
                        {t('memory.overview.recommendedReasonHits', { count: section.count })}
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-[#aa8166] transition-transform duration-200 group-hover:translate-x-0.5" />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="space-y-3">
                <div className="rounded-[1.35rem] border border-[#eadccf] bg-white/86 p-4 text-sm leading-6 text-[#735c4c]">
                  {t('memory.overview.recommendedEmpty')}
                </div>
                <div className="flex flex-wrap gap-2">
                  {overviewLinks.map((item) => (
                    <MemoryTag key={item.path}>{item.label}</MemoryTag>
                  ))}
                </div>
              </div>
            )}
          </MemoryWorkspacePanel>
        </div>

        <div className="mt-6 grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <Card className="rounded-[1.9rem] border-[#e6d7cb] bg-[rgba(255,252,248,0.94)] shadow-[0_16px_40px_-34px_rgba(112,80,52,0.4)]">
            <CardHeader>
              <CardTitle className="text-[#3f2d21]">{t('memory.overview.workspaceTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5 text-sm leading-6 text-[#6f5a4a]">
              <p>{t('memory.overview.workspaceBody')}</p>
              <div
                data-testid="memory-overview-layer-grid"
                className="grid gap-3 md:grid-cols-2"
              >
                {overviewLinks.map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    className="group rounded-[1.4rem] border border-[#eadccf] bg-white/88 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-[#d7bba3] hover:shadow-[0_14px_28px_-24px_rgba(104,76,50,0.45)]"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-[#34251c]">{item.label}</div>
                        <div className="mt-1 text-xs text-[#8b7260]">
                          {t('memory.overview.layerCardHint')}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xl font-semibold text-[#34251c]">{item.stat}</div>
                        <ArrowRight className="ml-auto mt-2 h-4 w-4 text-[#aa8166] transition-transform duration-200 group-hover:translate-x-0.5" />
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
              <div className="rounded-[1.4rem] border border-dashed border-[#dcc7b5] bg-[rgba(247,239,231,0.8)] p-4 text-[#785f4e]">
                {t('memory.overview.workspaceHint')}
              </div>
            </CardContent>
          </Card>

          <Card
            data-testid="memory-overview-recent-changes"
            className="rounded-[1.9rem] border-[#e6d7cb] bg-[rgba(255,252,248,0.94)] shadow-[0_16px_40px_-34px_rgba(112,80,52,0.4)]"
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[#3f2d21]">
                <Sparkles className="h-4 w-4 text-primary" />
                {t('memory.overview.recentChangesTitle')}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-[#6f5a4a]">
              <p>{t('memory.overview.statsBody')}</p>
              <div className="space-y-3">
                {recentChanges.map((item) => (
                  <div
                    key={item.title}
                    className="rounded-[1.3rem] border border-[#ecdcd0] bg-[rgba(250,245,239,0.92)] px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-[#3b2b20]">{item.title}</div>
                      <div className="text-lg font-semibold text-[#7d5f49]">{item.value}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="rounded-[1.4rem] border border-[#eadccf] bg-white/85 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-[#8f7460]">
                  {t('memory.overview.statsTitle')}
                </div>
                <div className="mt-2 text-sm leading-6">{t('memory.overview.asideBody')}</div>
              </div>
            </CardContent>
          </Card>
        </div>
      </MemoryPageFrame>

      <ClearMemoryDialog
        open={clearDialogOpen}
        onOpenChange={setClearDialogOpen}
        confirmText={clearConfirmText}
        onConfirmTextChange={setClearConfirmText}
        clearing={clearing}
        onConfirm={handleClearConfirm}
      />
    </>
  );
};

const OverviewMetric = ({ label, value }: { label: string; value: number }) => (
  <Card className="rounded-[1.5rem] border-[#e7d8cc] bg-[rgba(255,251,247,0.9)] shadow-[0_12px_24px_-24px_rgba(100,72,49,0.4)]">
    <CardContent className="pt-5">
      <div className="text-3xl font-semibold text-[#34251c]">{value}</div>
      <div className="mt-2 text-sm text-[#7c6554]">{label}</div>
    </CardContent>
  </Card>
);

const describeSearchItem = (item: Record<string, unknown> | undefined): string => {
  if (!item) return '';

  const previewKeys = [
    'raw_content',
    'canonical_name',
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
