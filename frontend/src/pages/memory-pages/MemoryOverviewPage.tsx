import { useTranslation } from 'react-i18next';
import { Search, Sparkles, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { ClearMemoryDialog } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';

export const MemoryOverviewPage = () => {
  const { t } = useTranslation('app');
  const {
    loading,
    stats,
    searchQuery,
    setSearchQuery,
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

  return (
    <>
      <MemoryPageFrame
        title={t('memory.nav.overview')}
        description={t('memory.overview.subtitle')}
        actions={(
          <>
            <Button variant="outline" onClick={() => void refreshAll()} disabled={loading}>
              {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
              {t('memory.refresh')}
            </Button>
            <Button variant="destructive" onClick={handleClearRequest}>
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
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('memory.searchPlaceholder')}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      void handleSearch();
                    }
                  }}
                />
                <Button onClick={() => void handleSearch()} disabled={searching}>
                  {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
                  <span className="ml-2">{t('memory.search')}</span>
                </Button>
              </div>
            </div>
          </div>
        )}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <OverviewMetric label={t('memory.l0.activeSessions')} value={stats.l0.active_sessions} />
          <OverviewMetric label={t('memory.l1.totalEvents')} value={stats.l1.event_count} />
          <OverviewMetric label={t('memory.l2.relationCount')} value={stats.l2.relation_count} />
          <OverviewMetric label={t('memory.l3.summaryCount')} value={stats.l3.summary_count} />
          <OverviewMetric label={t('memory.l4.skillCount')} value={stats.l4.skill_count} />
        </div>

        <div className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <Card className="border-dashed border-border/50 bg-background/75">
            <CardHeader>
              <CardTitle>{t('memory.overview.workspaceTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
              <p>{t('memory.overview.workspaceBody')}</p>
              <div className="rounded-2xl border border-border/40 bg-muted/20 p-4">
                {t('memory.overview.workspaceHint')}
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/40 bg-background/75">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                {t('memory.overview.statsTitle')}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>{t('memory.overview.statsBody')}</p>
              <ul className="space-y-2">
                <li>{t('memory.nav.workbench')}</li>
                <li>{t('memory.nav.events')}</li>
                <li>{t('memory.nav.knowledge')}</li>
                <li>{t('memory.nav.reflection')}</li>
                <li>{t('memory.nav.skills')}</li>
              </ul>
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
  <Card className="border-border/40 bg-background/75">
    <CardContent className="pt-5">
      <div className="text-3xl font-semibold text-foreground">{value}</div>
      <div className="mt-2 text-sm text-muted-foreground">{label}</div>
    </CardContent>
  </Card>
);

export default MemoryOverviewPage;
