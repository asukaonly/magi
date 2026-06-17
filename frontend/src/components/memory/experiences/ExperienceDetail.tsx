import { useState } from 'react';
import { EyeOff, Layers, MapPin, Sparkles, Tags, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type {
  L2EpisodeWithSummary,
  L2ExperienceReviewDetail,
  L2ExperienceWithReview,
} from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import EpisodeEventList from '../episodes/EpisodeEventList';
import {
  formatEpisodeTimeRange,
  getEpisodeDisplayTitle,
} from '../episodes/EpisodeRow';
import {
  formatExperienceTag,
  getExperienceDescription,
  getExperienceEntityLabels,
} from './ExperienceRow';

type ExperienceReviewLike = L2ExperienceWithReview | L2ExperienceReviewDetail;

const MEMORY_INFO_PANEL_CLASS = 'rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]';

const normalizeList = (items: string[] | null | undefined): string[] => (
  Array.isArray(items)
    ? items.map(formatExperienceTag).filter((item) => Boolean(item && item.trim()))
    : []
);

const getEpisodeDescription = (episode: L2EpisodeWithSummary): string => (
  String(
    episode.user_note ||
    episode.display_description ||
    episode.episode_summary?.content ||
    episode.summary ||
    episode.slice_narrative ||
    ''
  ).trim()
);

export function ExperienceDetail({
  experience,
  title,
  detailLoading,
  onRenameTitle,
  onEditDescription,
  onRegenerate,
  onHide,
}: {
  experience: ExperienceReviewLike;
  title: string;
  detailLoading: boolean;
  onRenameTitle: (title: string) => Promise<void>;
  onEditDescription: (description: string) => Promise<void>;
  onRegenerate: () => Promise<void>;
  onHide: () => Promise<void>;
}) {
  const { t, i18n } = useTranslation('app');
  const detail = experience as L2ExperienceReviewDetail;
  const events = Array.isArray(detail.events) ? detail.events : [];
  const sourceEpisodes = Array.isArray(detail.source_episodes) ? detail.source_episodes : [];
  const description = getExperienceDescription(experience);
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${experience.experience_type || 'activity'}`, {
    defaultValue: experience.experience_type || '',
  });
  const [renameOpen, setRenameOpen] = useState(false);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [hideOpen, setHideOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState(title);
  const [descriptionDraft, setDescriptionDraft] = useState(description);
  const [saving, setSaving] = useState(false);

  const openRename = () => {
    setTitleDraft(title);
    setRenameOpen(true);
  };

  const openDescription = () => {
    setDescriptionDraft(description);
    setDescriptionOpen(true);
  };

  const saveTitle = async () => {
    setSaving(true);
    try {
      await onRenameTitle(titleDraft.trim());
      setRenameOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const saveDescription = async () => {
    setSaving(true);
    try {
      await onEditDescription(descriptionDraft.trim());
      setDescriptionOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const runRegenerate = async () => {
    setSaving(true);
    try {
      await onRegenerate();
      setRegenerateOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const requestRegenerate = () => {
    if (experience.user_note) {
      setRegenerateOpen(true);
      return;
    }
    void runRegenerate();
  };

  const runHide = async () => {
    setSaving(true);
    try {
      await onHide();
      setHideOpen(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-w-0">
      <header className="border-b border-[hsl(var(--memory-divider)/0.62)] px-5 py-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {typeLabel ? (
                <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-body))]">
                  {typeLabel}
                </Badge>
              ) : null}
              {experience.user_pinned ? (
                <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-accent)/0.24)] bg-[hsl(var(--memory-accent-soft)/0.62)] text-[hsl(var(--memory-title))]">
                  {t('memory.episodes.fields.pinned')}
                </Badge>
              ) : null}
            </div>
            <h2 className="mt-2 break-words text-xl font-semibold leading-7 text-[hsl(var(--memory-title))]">{title}</h2>
            {range ? <p className="mt-1 text-sm text-[hsl(var(--memory-muted))]">{range}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={openRename}>{t('memory.episodes.actions.rename')}</Button>
            <Button variant="outline" size="sm" onClick={openDescription}>{t('memory.episodes.actions.editDescription')}</Button>
            <Button variant="outline" size="sm" onClick={requestRegenerate}>{t('memory.episodes.actions.regenerateDescription')}</Button>
            <Button variant="outline" size="sm" onClick={() => setHideOpen(true)}>
              <EyeOff className="h-4 w-4" aria-hidden="true" />
              {t('memory.episodes.actions.hide')}
            </Button>
          </div>
        </div>
      </header>

      <div className="space-y-5 px-5 py-5">
        {detailLoading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
            <Sparkles className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {t('memory.episodes.sections.recap')}
          </h3>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">
            {description || t('memory.episodes.noRecap')}
          </p>
        </section>

        <div className="grid gap-3 md:grid-cols-3">
          <TagGroup
            icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.entities')}
            values={getExperienceEntityLabels(experience)}
          />
          <TagGroup
            icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.places')}
            values={normalizeList(experience.primary_place_ids)}
          />
          <TagGroup
            icon={<Tags className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.topics')}
            values={normalizeList(experience.primary_topic_keys)}
          />
        </div>

        <SourceEpisodeList episodes={sourceEpisodes} />
        <EpisodeEventList events={events} />
      </div>

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('memory.episodes.dialogs.renameTitle')}</DialogTitle>
            <DialogDescription>{t('memory.episodes.dialogs.renameDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 px-6 pb-2">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.title')}</span>
              <Input
                aria-label={t('memory.episodes.fields.title')}
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                className="border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))]"
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRenameOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void saveTitle()} disabled={saving}>
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={descriptionOpen} onOpenChange={setDescriptionOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('memory.episodes.dialogs.editDescriptionTitle')}</DialogTitle>
            <DialogDescription>{t('memory.episodes.dialogs.editDescriptionDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 px-6 pb-2">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.description')}</span>
              <Textarea
                aria-label={t('memory.episodes.fields.description')}
                value={descriptionDraft}
                onChange={(event) => setDescriptionDraft(event.target.value)}
                className="min-h-[160px] border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))]"
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDescriptionOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void saveDescription()} disabled={saving}>
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={regenerateOpen} onOpenChange={setRegenerateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('memory.episodes.dialogs.regenerateTitle')}</DialogTitle>
            <DialogDescription>{t('memory.episodes.dialogs.regenerateDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRegenerateOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void runRegenerate()} disabled={saving}>
              {saving ? t('common.saving') : t('memory.episodes.actions.confirmRegenerate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={hideOpen} onOpenChange={setHideOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('memory.episodes.dialogs.hideTitle')}</DialogTitle>
            <DialogDescription>{t('memory.episodes.dialogs.hideDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setHideOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void runHide()} disabled={saving}>
              {saving ? t('common.saving') : t('memory.episodes.actions.confirmHide')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SourceEpisodeList({ episodes }: { episodes: L2EpisodeWithSummary[] }) {
  const { t, i18n } = useTranslation('app');
  return (
    <section>
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <Layers className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.sourceEpisodes')}
      </h3>
      <div className="mt-3 overflow-hidden rounded-xl border border-[hsl(var(--memory-border)/0.52)]">
        {episodes.length === 0 ? (
          <div className="px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noSourceEpisodes')}</div>
        ) : episodes.map((episode) => {
          const title = getEpisodeDisplayTitle(episode, t('memory.episodes.awaitingLabel'));
          const summary = getEpisodeDescription(episode);
          const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
          return (
            <article key={episode.episode_id} className="border-t border-[hsl(var(--memory-divider)/0.54)] px-4 py-3 first:border-t-0">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h4 className="break-words text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h4>
                  {summary ? (
                    <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{summary}</p>
                  ) : null}
                </div>
                <div className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">
                  {range}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function TagGroup({ icon, title, values }: { icon: ReactNode; title: string; values: string[] }) {
  const { t } = useTranslation('app');
  return (
    <section className="min-w-0 rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.46)] px-3 py-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <span className="text-[hsl(var(--memory-accent))]">{icon}</span>
        {title}
      </h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {values.length > 0 ? values.map((value) => (
          <span key={value} className="min-w-0 rounded-md border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
            {value}
          </span>
        )) : (
          <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noTags')}</span>
        )}
      </div>
    </section>
  );
}

export default ExperienceDetail;
