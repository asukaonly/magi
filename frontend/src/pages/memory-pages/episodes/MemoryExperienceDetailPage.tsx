import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';
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

  const loadExperience = useCallback(async () => {
    if (!experienceId) {
      setExperience(null);
      setNotFound(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setNotFound(false);
    try {
      const payload = await memoryApi.getExperience(experienceId);
      setExperience(payload);
    } catch {
      setExperience(null);
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [experienceId]);

  useEffect(() => {
    void loadExperience();
  }, [loadExperience]);

  const applyExperienceUpdate = useCallback((updated: L2ExperienceReviewDetail) => {
    setExperience((current) => (
      current && current.experience_id === updated.experience_id
        ? { ...current, ...updated }
        : updated
    ));
  }, []);

  const renameExperience = async (title: string) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      user_label: title,
    });
    applyExperienceUpdate({
      ...updated,
      display_title: updated.user_label || title,
    });
  };

  const editDescription = async (description: string) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      user_note: description,
    });
    applyExperienceUpdate({
      ...updated,
      display_description: updated.user_note || description,
    });
  };

  const changeCover = async (file: File) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.uploadExperienceCover(experience.experience_id, file);
    applyExperienceUpdate(updated);
  };

  const regenerateDescription = async () => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.regenerateExperienceReview(experience.experience_id);
    applyExperienceUpdate(updated);
  };

  const hideExperience = async () => {
    if (!experience) {
      return;
    }
    await memoryApi.hideExperience(experience.experience_id);
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
          experience={experience}
          title={title}
          detailLoading={false}
          onRenameTitle={renameExperience}
          onEditDescription={editDescription}
          onChangeCover={changeCover}
          onRegenerate={regenerateDescription}
          onHide={hideExperience}
          toolbarStart={backButton}
          variant="sheet"
        />
      )}
    </MemoryPageFrame>
  );
};
