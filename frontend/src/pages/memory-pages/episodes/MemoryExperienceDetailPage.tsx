import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { useAppNavigate as useNavigate } from '@/hooks/useAppNavigate';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { ArrowLeft } from 'lucide-react';
import {
  memoryApi,
  type L2ExperienceReviewDetail,
} from '@/api/modules/memory';
import ExperienceDetail from '@/components/memory/experiences/ExperienceDetail';
import { getExperienceDisplayTitle } from '@/components/memory/experiences/ExperienceRow';
import { Button } from '@/components/ui/button';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from '../MemoryPageFrame';

export const MemoryExperienceDetailPage = () => {
  const { t, i18n } = useTranslation('app');
  const { experienceId } = useParams<{ experienceId: string }>();
  const navigate = useNavigate();
  const [experience, setExperience] = useState<L2ExperienceReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const beginRead = useRequestOwner(experienceId ?? '');
  const beginWrite = useRequestOwner(experienceId ?? '');
  const savedGeneration = useRef(0);
  const loadExperience = useCallback(async (silent = false) => {
    const isCurrent = beginRead('experience');
    const generation = savedGeneration.current;
    if (!experienceId) {
      setExperience(null);
      setNotFound(true);
      setLoading(false);
      return;
    }
    if (!silent) { setLoading(true); setNotFound(false); }
    try {
      const payload = await memoryApi.getExperience(experienceId);
      if (!isCurrent() || generation !== savedGeneration.current) return;
      setExperience(payload);
      setNotFound(false);
    } catch {
      if (isCurrent() && !silent) { setExperience(null); setNotFound(true); }
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [experienceId, beginRead]);

  useEffect(() => {
    void loadExperience();
  }, [loadExperience]);

  useCenterRefresh(() => loadExperience(true));

  const applyExperienceUpdate = useCallback((updated: L2ExperienceReviewDetail) => {
    savedGeneration.current += 1;
    beginRead('experience');
    setExperience((current) => (
      current && current.experience_id === updated.experience_id
        ? { ...current, ...updated }
        : updated
    ));
  }, [beginRead]);

  const renameExperience = async (title: string, revision: string) => {
    if (!experience) {
      return;
    }
    const current = beginWrite('mutation');
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      expected_revision: revision,
      user_label: title,
    });
    if (!current()) return;
    applyExperienceUpdate(updated);
  };

  const editDescription = async (description: string, revision: string) => {
    if (!experience) {
      return;
    }
    const current = beginWrite('mutation');
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      expected_revision: revision,
      user_note: description,
    });
    if (!current()) return;
    applyExperienceUpdate(updated);
  };

  const changeCover = async (file: File, revision: string) => {
    if (!experience) {
      return;
    }
    const current = beginWrite('mutation');
    const updated = await memoryApi.uploadExperienceCover(experience.experience_id, file, revision);
    if (!current()) return;
    applyExperienceUpdate(updated);
  };

  const regenerateDescription = async () => {
    if (!experience) {
      return;
    }
    const current = beginWrite('mutation');
    const updated = await memoryApi.regenerateExperienceReview(experience.experience_id);
    if (!current()) return;
    applyExperienceUpdate(updated);
  };

  const hideExperience = async () => {
    if (!experience) {
      return;
    }
    const current = beginWrite('mutation');
    await memoryApi.hideExperience(experience.experience_id);
    if (!current()) return;
    navigate('/memory/episodes');
  };

  const title = experience
    ? getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'), i18n.language)
    : '';
  const backButton = (
    <Button
      type="button"
      variant="ghost"
      className="-ml-2 h-8 rounded-md px-2 text-xs font-medium text-[hsl(var(--memory-muted))] hover:bg-[hsl(var(--memory-panel-subtle)/0.82)] hover:text-[hsl(var(--memory-title))]"
      onClick={() => navigate('/memory/episodes')}
    >
      <ArrowLeft className="h-4 w-4" aria-hidden="true" />
      {t('memory.episodes.actions.backToList')}
    </Button>
  );

  return (
    <MemoryPageFrame
      title={title || t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-3 px-4 pb-5 pt-3"
      contentClassName="pb-8"
    >
      {loading ? (
        <>
          <div>{backButton}</div>
          <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
        </>
      ) : notFound || !experience ? (
        <>
          <div>{backButton}</div>
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.detailNotFound')}</div>
        </>
      ) : (
        <ExperienceDetail
          key={experience.experience_id}
          experience={experience}
          title={title}
          detailLoading={false}
          onRenameTitle={renameExperience}
          onEditDescription={editDescription}
          onChangeCover={changeCover}
          onRegenerate={regenerateDescription}
          onHide={hideExperience}
          onReload={loadExperience}
          toolbarStart={backButton}
          variant="sheet"
        />
      )}
    </MemoryPageFrame>
  );
};
