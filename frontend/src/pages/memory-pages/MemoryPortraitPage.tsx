import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { memoryPortraitSelfApi, type SelfPortraitPayload } from '@/api/modules/memoryPortraitSelf';
import { memoryApi } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import PortraitWorldMap from '@/components/memory/portrait/PortraitWorldMap';
import PortraitReviewQueue from '@/components/memory/portrait/PortraitReviewQueue';
import PortraitRecentState from '@/components/memory/portrait/PortraitRecentState';
import { buildPortraitViewModel } from '@/components/memory/portrait/portraitGrouping';
import MemoryPageFrame from './MemoryPageFrame';
import { DEFAULT_USER_ID } from '@/constants';

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
  const [payload, setPayload] = useState<SelfPortraitPayload | null>(null);

  const loadPortrait = useCallback(async () => {
    try {
      setPayload(await memoryPortraitSelfApi.get(DEFAULT_USER_ID));
    } catch {
      setPayload(null);
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

  const handleReject = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'rejected');
    await loadPortrait();
  };

  const handleCorrect = async (assertionId: string, value: string) => {
    await memoryApi.correctAssertion(assertionId, value, 'portrait_review');
    await loadPortrait();
  };

  if (!payload) {
    return (
      <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')} hideHeader>
        {null}
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
            <PortraitWorldMap groups={viewModel.worldGroups} totalCount={viewModel.totalUnderstandingCount} />
            <PortraitReviewQueue
              items={viewModel.reviewItems}
              onConfirm={handleConfirm}
              onReject={handleReject}
              onCorrect={handleCorrect}
            />
            <PortraitRecentState items={viewModel.recentItems} />
          </>
        ) : null}
      </div>
    </MemoryPageFrame>
  );
};

export default MemoryPortraitPage;
