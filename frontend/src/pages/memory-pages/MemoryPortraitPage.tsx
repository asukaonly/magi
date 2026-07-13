import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryPortraitSelfApi, type SelfPortraitPayload } from '@/api/modules/memoryPortraitSelf';
import { memoryApi } from '@/api/modules/memory';
import PortraitWorldMap from '@/components/memory/portrait/PortraitWorldMap';
import PortraitReviewQueue from '@/components/memory/portrait/PortraitReviewQueue';
import PortraitRecentState from '@/components/memory/portrait/PortraitRecentState';
import { buildPortraitViewModel } from '@/components/memory/portrait/portraitGrouping';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { DEFAULT_USER_ID } from '@/constants';

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
        <div className="space-y-4">
          {viewModel ? (
            <PortraitWorldMap groups={viewModel.worldGroups} totalCount={viewModel.totalUnderstandingCount} />
          ) : null}
          <div className={MEMORY_EMPTY_PANEL_CLASS}>
            <p className="text-sm">{payload.cold_start_line ?? t('memory.portrait.coldStartFallback')}</p>
          </div>
        </div>
      </MemoryPageFrame>
    );
  }

  return (
    <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')} hideHeader>
      <div className="space-y-4">
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
