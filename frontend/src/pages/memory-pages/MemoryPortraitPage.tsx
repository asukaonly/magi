import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, X } from 'lucide-react';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import type { PortraitObservation, PortraitPayload } from '@/api/modules/memoryPortrait';
import { memoryApi } from '@/api/modules/memory';
import PortraitSegment from '@/components/memory/portrait/PortraitSegment';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { Button } from '@/components/ui/button';
import { DEFAULT_USER_ID } from '@/constants';

const ASSERTION_REF_PATTERN = /^[0-9a-f-]{20,}$/i;

const extractAssertionId = (obs: PortraitObservation): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith('assertion:') || ASSERTION_REF_PATTERN.test(r));
  if (!ref) return null;
  return ref.startsWith('assertion:') ? ref.slice('assertion:'.length) : ref;
};

const groupByPrefix = (observations: PortraitObservation[], prefix: string) =>
  observations.filter((obs) => obs.basis_refs.some((ref) => ref.startsWith(prefix)));

export const MemoryPortraitPage = () => {
  const { t } = useTranslation('app');
  const [payload, setPayload] = useState<PortraitPayload | null>(null);

  useEffect(() => {
    void memoryPortraitSelfApi.get(DEFAULT_USER_ID).then(setPayload).catch(() => setPayload(null));
  }, []);

  const handleConfirm = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'confirmed');
  };
  const handleReject = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'rejected');
  };

  const renderItem = (obs: PortraitObservation) => {
    const assertionId = extractAssertionId(obs);
    return (
      <div className="flex items-start justify-between gap-3">
        <p>{obs.text}</p>
        {assertionId ? (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" aria-label={t('memory.stories.actions.confirm')} onClick={() => void handleConfirm(assertionId)}>
              <Check className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="sm" aria-label={t('memory.stories.actions.reject')} onClick={() => void handleReject(assertionId)}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null}
      </div>
    );
  };

  if (!payload) {
    return <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>{null}</MemoryPageFrame>;
  }

  if (payload.is_cold_start) {
    return (
      <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <p className="text-sm">{payload.cold_start_line ?? t('memory.portrait.coldStartFallback')}</p>
        </div>
      </MemoryPageFrame>
    );
  }

  const identityObs = [
    ...groupByPrefix(payload.observations, 'real_name'),
    ...groupByPrefix(payload.observations, 'preferred_form_of_address'),
    ...groupByPrefix(payload.observations, 'home_location'),
  ];
  const stateObs = groupByPrefix(payload.observations, 'state:');
  const preferenceObs = [
    ...groupByPrefix(payload.observations, 'preference:'),
    ...groupByPrefix(payload.observations, 'communication:'),
  ];
  const impressionObs = payload.observations.filter((obs) => obs.kind === 'reflection');
  const relationshipObs = payload.observations.filter((obs) => obs.kind === 'relationship');

  return (
    <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>
      <div className="space-y-3">
        <PortraitSegment title={t('memory.portrait.segments.identity')} observations={identityObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.state')} observations={stateObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.preferences')} observations={preferenceObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.relationships')} observations={relationshipObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.impression')} observations={impressionObs} renderItem={renderItem} />
      </div>
    </MemoryPageFrame>
  );
};

export default MemoryPortraitPage;
