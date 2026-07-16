import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { memoryPortraitSelfApi, type SelfPortraitPayload } from '@/api/modules/memoryPortraitSelf';
import { memoryApi } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import PortraitWorldMap from '@/components/memory/portrait/PortraitWorldMap';
import PortraitReviewQueue from '@/components/memory/portrait/PortraitReviewQueue';
import PortraitRecentState from '@/components/memory/portrait/PortraitRecentState';
import { buildPortraitViewModel, type PortraitDisplayItem } from '@/components/memory/portrait/portraitGrouping';
import MemoryPageFrame from './MemoryPageFrame';
import { DEFAULT_USER_ID } from '@/constants';
import { useChatShellStore } from '@/stores';

const PortraitEmptyState = () => {
  const { t } = useTranslation('app');

  return (
    <section
      data-testid="memory-portrait-empty"
      className="mx-auto flex min-h-[clamp(32rem,72vh,46rem)] w-full max-w-5xl items-start px-2 pt-[clamp(5rem,14vh,8.5rem)]"
    >
      <div className="max-w-xl">
        <h1 className="text-[clamp(1.7rem,2.8vw,2.25rem)] font-semibold tracking-[-0.035em] text-[hsl(var(--memory-title))]">
          {t('memory.portrait.empty.title')}
        </h1>
        <p className="mt-4 text-sm leading-7 text-[hsl(var(--memory-body))]">
          {t('memory.portrait.empty.body')}
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-2">
          <Button asChild size="sm" variant="secondary" className="rounded-lg px-4">
            <Link to="/chat">{t('memory.portrait.empty.actions.chat')}</Link>
          </Button>
          <Button asChild size="sm" variant="ghost" className="rounded-lg px-4">
            <Link to="/memory/sources">{t('memory.portrait.empty.actions.sources')}</Link>
          </Button>
        </div>
        <p className="mt-8 text-xs leading-5 text-[hsl(var(--memory-muted))]">
          {t('memory.portrait.empty.helper')}
        </p>
      </div>
    </section>
  );
};

export const MemoryPortraitPage = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((state) => state.setSettingsNavigationIntent);
  const [payload, setPayload] = useState<SelfPortraitPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);
  const [correctionAction, setCorrectionAction] = useState<'replace' | 'remove'>('replace');

  const loadPortrait = useCallback(async () => {
    setLoading(true);
    try {
      setPayload(await memoryPortraitSelfApi.get(DEFAULT_USER_ID));
      setLoadError(false);
      return true;
    } catch {
      setLoadError(true);
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPortrait();
  }, [loadPortrait]);

  const viewModel = useMemo(
    () => (payload ? buildPortraitViewModel(payload.self_view) : null),
    [payload]
  );

  const handleConfirm = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'confirmed');
    await loadPortrait();
  };

  const openCorrection = (item: PortraitDisplayItem, action: 'replace' | 'remove' = 'replace') => {
    if (!item.assertionId) return;
    setCorrectionAction(action);
    setCorrectionTarget({
      kind: 'assertion',
      id: item.assertionId,
      statement: item.text,
      currentValue: item.correctionValue ?? item.text,
      displayValue: item.text,
      expectedUpdatedAt: item.updatedAt ?? undefined,
    });
  };

  if (!payload) {
    return (
      <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')} hideHeader>
        <section className="mx-auto flex min-h-[clamp(28rem,68vh,42rem)] w-full max-w-5xl items-center justify-center px-4">
          {loading ? (
            <p role="status" className="flex items-center gap-2 text-sm text-[hsl(var(--memory-muted))]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('memory.portrait.loading', { defaultValue: '正在读取关于你的内容…' })}
            </p>
          ) : loadError ? (
            <div className="max-w-md text-center">
              <h1 className="text-xl font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.portrait.loadFailed.title', { defaultValue: '暂时没能读取关于你的内容' })}
              </h1>
              <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-body))]">
                {t('memory.portrait.loadFailed.body', { defaultValue: '已有内容没有丢失，请稍后再试。' })}
              </p>
              <Button className="mt-5" variant="secondary" onClick={() => void loadPortrait()}>
                {t('memory.portrait.loadFailed.retry', { defaultValue: '重新读取' })}
              </Button>
            </div>
          ) : null}
        </section>
      </MemoryPageFrame>
    );
  }

  if (payload.is_cold_start) {
    return (
      <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')} hideHeader>
        <PortraitEmptyState />
      </MemoryPageFrame>
    );
  }

  return (
    <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')} hideHeader>
      <div className="mx-auto max-w-5xl space-y-14 px-2 pb-10 pt-3">
        {viewModel ? (
          <>
            <PortraitWorldMap
              groups={viewModel.worldGroups}
              totalCount={viewModel.totalUnderstandingCount}
              onCorrect={(assertionId) => {
                const item = viewModel.worldGroups
                  .flatMap((group) => group.items)
                  .find((candidate) => candidate.assertionId === assertionId);
                if (item) openCorrection(item);
              }}
              onEditProfile={() => {
                setSettingsNavigationIntent({ section: 'personalProfile' });
                setActivePanel('settings');
              }}
            />
            <PortraitReviewQueue
              items={viewModel.reviewItems}
              onConfirm={handleConfirm}
              onRequestCorrection={openCorrection}
            />
            <PortraitRecentState items={viewModel.recentItems} />
          </>
        ) : null}
      </div>
      <MemoryCorrectionDialog
        open={correctionTarget !== null}
        target={correctionTarget}
        initialRecordErrorAction={correctionAction}
        onOpenChange={(open) => {
          if (!open) setCorrectionTarget(null);
        }}
        onSaved={async () => {
          if (!await loadPortrait()) {
            toast.warning(t('memory.portrait.refreshFailed', {
              defaultValue: '修正已经生效，但“关于你”暂时没有刷新。',
            }));
          }
        }}
        onConflict={async () => {
          if (!await loadPortrait()) {
            toast.warning(t('memory.correction.latestRefreshFailed', {
              defaultValue: '暂时无法读取最新内容，请稍后再试。',
            }));
          }
        }}
      />
    </MemoryPageFrame>
  );
};

export default MemoryPortraitPage;
