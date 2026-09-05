import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  CalendarRange,
  EyeOff,
  ImageIcon,
  Pencil,
  RefreshCw,
  Star,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type {
  L2EpisodeEventPreview,
  L2ExperienceReviewDetail,
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
import { formatMemoryTimeRange } from '@/utils/memory-time';
import {
  getExperienceDescription,
  getExperienceEntityLabels,
} from './ExperienceRow';
import { cn } from '@/lib/utils';
import {
  getExperienceCoverUrl,
  getReadableRecap,
  normalizeList,
  type ExperienceReviewLike,
} from './ExperienceDetailModel';
import { RelatedObjectsPanel } from './ExperienceRelatedObjects';
import { SourceEpisodeList } from './ExperienceSourceEpisodes';
import { resolveTimelineAssetUrl } from '@/utils/timelineAssetUrl';
import ExperienceHero from './ExperienceHero';

const DETAIL_INFO_PANEL_CLASS = 'rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]';

export function ExperienceDetail({
  experience,
  title,
  detailLoading,
  onRenameTitle,
  onEditDescription,
  onChangeCover,
  onRegenerate,
  onHide,
  toolbarStart,
  variant = 'sheet',
}: {
  experience: ExperienceReviewLike;
  title: string;
  detailLoading: boolean;
  onRenameTitle: (title: string) => Promise<void>;
  onEditDescription: (description: string) => Promise<void>;
  onChangeCover?: (file: File) => Promise<void>;
  onRegenerate: () => Promise<void>;
  onHide: () => Promise<void>;
  toolbarStart?: ReactNode;
  variant?: 'sheet' | 'inline';
}) {
  const { t, i18n } = useTranslation('app');
  const isInline = variant === 'inline';
  const detail = experience as L2ExperienceReviewDetail;
  const events = Array.isArray(detail.events) ? detail.events : [];
  const sourceEpisodes = Array.isArray(detail.source_episodes) ? detail.source_episodes : [];
  const chapters = Array.isArray(detail.chapters) ? detail.chapters : [];
  const description = getExperienceDescription(experience);
  const range = formatMemoryTimeRange(experience.time_start, experience.time_end, i18n.language);
  const tags = [
    ...getExperienceEntityLabels(experience),
    ...normalizeList(experience.primary_place_ids),
    ...normalizeList(experience.primary_topic_keys),
  ].slice(0, 8);
  const readableRecap = getReadableRecap(experience, description, title, tags, i18n.language);
  const coverUrl = getExperienceCoverUrl(sourceEpisodes);
  const userCoverUrl = resolveTimelineAssetUrl(experience.user_cover_asset_ref);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const experienceId = String(experience.experience_id || '');
  const localCoverUrlRef = useRef<string | null>(null);
  const [localCoverUrl, setLocalCoverUrl] = useState<string | null>(null);
  const [coverSaving, setCoverSaving] = useState(false);
  const displayCoverUrl = localCoverUrl || userCoverUrl || coverUrl;
  const eventsByEpisode = new Map<string, L2EpisodeEventPreview[]>();
  events.forEach((event) => {
    eventsByEpisode.set(event.episode_id, [...(eventsByEpisode.get(event.episode_id) ?? []), event]);
  });
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

  useEffect(() => {
    if (localCoverUrlRef.current) {
      URL.revokeObjectURL(localCoverUrlRef.current);
      localCoverUrlRef.current = null;
    }
    setLocalCoverUrl(null);
  }, [experienceId]);

  useEffect(() => () => {
    if (localCoverUrlRef.current) {
      URL.revokeObjectURL(localCoverUrlRef.current);
      localCoverUrlRef.current = null;
    }
  }, []);

  const replaceLocalCoverUrl = (nextUrl: string | null) => {
    if (localCoverUrlRef.current && localCoverUrlRef.current !== nextUrl) {
      URL.revokeObjectURL(localCoverUrlRef.current);
    }
    localCoverUrlRef.current = nextUrl;
    setLocalCoverUrl(nextUrl);
  };

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

  const chooseCover = () => {
    fileInputRef.current?.click();
  };

  const updateCover = async (file: File | undefined) => {
    if (!file) {
      return;
    }
    const nextUrl = URL.createObjectURL(file);
    replaceLocalCoverUrl(nextUrl);
    if (!onChangeCover) {
      return;
    }
    setCoverSaving(true);
    try {
      await onChangeCover(file);
      replaceLocalCoverUrl(null);
    } catch {
      replaceLocalCoverUrl(null);
    } finally {
      setCoverSaving(false);
    }
  };

  const toolbarButtonClass = 'h-8 rounded-md border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.7)] px-2.5 text-xs font-medium text-[hsl(var(--memory-body))] shadow-none hover:bg-[hsl(var(--memory-panel-subtle)/0.82)] hover:text-[hsl(var(--memory-title))]';
  const hideButtonClass = 'h-8 rounded-md border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.7)] px-2.5 text-xs font-medium text-[hsl(var(--memory-body))] shadow-none hover:bg-[hsl(var(--destructive)/0.08)] hover:text-[hsl(var(--destructive))]';
  const entityLabels = getExperienceEntityLabels(experience);
  const placeLabels = normalizeList(experience.primary_place_ids);
  const topicLabels = normalizeList(experience.primary_topic_keys);
  const hasRelatedObjects = entityLabels.length > 0 || placeLabels.length > 0 || topicLabels.length > 0;

  return (
    <div
      className={cn(
        'min-w-0',
        isInline && 'overflow-hidden rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.82)] p-5'
      )}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        aria-label={t('memory.episodes.actions.changeCoverFile')}
        className="sr-only"
        onChange={(event) => {
          void updateCover(event.currentTarget.files?.[0]);
          event.currentTarget.value = '';
        }}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">{toolbarStart}</div>
        <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
          <Button variant="outline" size="sm" className={toolbarButtonClass} onClick={chooseCover} disabled={coverSaving}>
            <ImageIcon className="h-4 w-4" aria-hidden="true" />
            {coverSaving ? t('common.saving') : t('memory.episodes.actions.changeCover')}
          </Button>
          <Button variant="outline" size="sm" className={toolbarButtonClass} onClick={openRename}>
            <Pencil className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.actions.rename')}
          </Button>
          <Button variant="outline" size="sm" className={toolbarButtonClass} onClick={openDescription}>
            <Pencil className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.actions.editDescription')}
          </Button>
          <Button variant="outline" size="sm" className={toolbarButtonClass} onClick={requestRegenerate}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.actions.regenerateDescription')}
          </Button>
          <Button variant="outline" size="sm" className={hideButtonClass} onClick={() => setHideOpen(true)}>
            <EyeOff className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.actions.hide')}
          </Button>
        </div>
      </div>

      <ExperienceHero
        coverUrl={displayCoverUrl}
        title={title}
        titleLevel={1}
        variant={variant}
        className="mt-3"
        topContent={(
          <div className="flex flex-wrap items-center gap-2">
            {experience.user_pinned ? (
              <Badge variant="outline" className="rounded-full border-[hsl(var(--memory-accent)/0.26)] bg-[hsl(var(--memory-panel-elevated)/0.74)] text-[hsl(var(--memory-title))]">
                <Star className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.episodes.sections.featured')}
              </Badge>
            ) : null}
            {typeLabel ? (
              <Badge variant="outline" className="rounded-full border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-panel-elevated)/0.68)] text-[hsl(var(--memory-body))]">
                {typeLabel}
              </Badge>
            ) : null}
            {range ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--memory-panel-elevated)/0.66)] px-2.5 py-1">
                <CalendarRange className="h-3.5 w-3.5" aria-hidden="true" />
                {range}
              </span>
            ) : null}
          </div>
        )}
        metadata={(
          <>
            <span className="inline-flex items-center gap-1">
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              {t('memory.episodes.episodeCount', { count: experience.source_episode_count ?? 0 })}
            </span>
            <span>{t('memory.episodes.eventCount', { count: experience.source_event_count ?? 0 })}</span>
          </>
        )}
        recapLabel={t('memory.episodes.sections.recap')}
        recap={readableRecap || t('memory.episodes.noRecap')}
      />

      <main className="mt-4 min-w-0 space-y-5">
        {hasRelatedObjects ? (
          <RelatedObjectsPanel
            entities={entityLabels}
            places={placeLabels}
            topics={topicLabels}
          />
        ) : null}
        {detailLoading ? <div className={DETAIL_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
        <SourceEpisodeList episodes={sourceEpisodes} eventsByEpisode={eventsByEpisode} chapters={chapters} />
      </main>

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


export default ExperienceDetail;
