import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  CalendarRange,
  EyeOff,
  GitMerge,
  ImageIcon,
  Layers,
  MapPin,
  Pencil,
  Quote,
  RefreshCw,
  Star,
  Tags,
  UserRound,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type {
  L2EpisodeWithSummary,
  L2EpisodeEventPreview,
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
import { formatEpisodeTimeRange } from '../episodes/EpisodeRow';
import {
  formatExperienceTag,
  getExperienceDescription,
  getExperienceEntityLabels,
} from './ExperienceRow';
import { cn } from '@/lib/utils';
import { resolveTimelineAssetUrl } from '@/utils/timelineAssetUrl';

type ExperienceReviewLike = L2ExperienceWithReview | L2ExperienceReviewDetail;

const MEMORY_INFO_PANEL_CLASS = 'rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]';
const MACHINE_TITLE_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{16,}$|^[0-9A-HJKMNP-TV-Z]{12,}$/i;
const MECHANICAL_RECAP_PATTERNS = [
  /Chrome\s*(浏览|browsed)/i,
  /Google Search/i,
  /(访问|visited)\s*\d+\s*(次|times)/i,
  /;\s*Chrome/i,
];

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

const truncateText = (value: string, maxLength: number): string => {
  const text = value.trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trim()}…`;
};

const firstReadableSentence = (value: string): string => {
  const text = value.trim();
  if (!text) {
    return '';
  }
  const [sentence = text] = text.split(/(?<=[。！？.!?])\s+|[；;]\s*/);
  return truncateText(sentence.trim() || text, 150);
};

const isMechanicalRecap = (value: string): boolean => {
  const text = value.trim();
  if (!text) {
    return false;
  }
  const separatorCount = (text.match(/[；;]/g) || []).length;
  const patternHits = MECHANICAL_RECAP_PATTERNS.filter((pattern) => pattern.test(text)).length;
  return separatorCount >= 2 || patternHits >= 2;
};

const getReadableRecap = (
  experience: ExperienceReviewLike,
  rawDescription: string,
  title: string,
  tags: string[],
  locale: string
): string => {
  if (!rawDescription.trim()) {
    return '';
  }
  if (experience.user_note) {
    return firstReadableSentence(rawDescription);
  }
  if (!isMechanicalRecap(rawDescription) && rawDescription.trim().length <= 180) {
    return firstReadableSentence(rawDescription);
  }
  const subject = title || tags[0] || '';
  if (!subject) {
    return locale.startsWith('zh')
      ? '这段经历已经整理成一段可以回看的记录。'
      : 'This experience has been shaped into something you can revisit.';
  }
  return locale.startsWith('zh')
    ? `这段经历主要围绕「${subject}」展开。`
    : `This experience centers on ${subject}.`;
};

const getEpisodeEvents = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): L2EpisodeEventPreview[] => eventsByEpisode.get(episode.episode_id) ?? [];

const getEventPreviewText = (event: L2EpisodeEventPreview): string => (
  String(event.content_preview || '').trim()
);

const getSourceEpisodeFallbackFromEvents = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const event = getEpisodeEvents(episode, eventsByEpisode).find((item) => getEventPreviewText(item));
  return event ? firstReadableSentence(getEventPreviewText(event)) : '';
};

const getReadableSourceEpisodeTitle = (
  episode: L2EpisodeWithSummary,
  index: number,
  fallbackTemplate: string,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const values = [
    episode.user_label,
    episode.display_title,
    episode.episode_summary?.label,
    episode.label,
    episode.summary,
    episode.slice_narrative,
  ];
  const title = values.find((value) => typeof value === 'string' && value.trim())?.trim() ?? '';
  if (!title || MACHINE_TITLE_PATTERN.test(title)) {
    return getSourceEpisodeFallbackFromEvents(episode, eventsByEpisode)
      || fallbackTemplate.replace('{{index}}', String(index + 1));
  }
  return title;
};

const getReadableSourceEpisodeSummary = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const summary = getEpisodeDescription(episode);
  if (summary) {
    return summary;
  }
  return getEpisodeEvents(episode, eventsByEpisode)
    .map(getEventPreviewText)
    .filter(Boolean)
    .slice(0, 2)
    .map((item) => firstReadableSentence(item))
    .join(' / ');
};

const getExperienceCoverUrl = (episodes: L2EpisodeWithSummary[]): string | null => {
  for (const episode of episodes) {
    const url = resolveTimelineAssetUrl(episode.representative_asset_ref);
    if (url) {
      return url;
    }
  }
  return null;
};

const formatSourceLabel = (value: string | null | undefined): string => (
  String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim()
);

const formatEventTime = (value: number | null | undefined, locale: string): string => {
  if (typeof value !== 'number') {
    return '';
  }
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value * 1000));
};

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
  const description = getExperienceDescription(experience);
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
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

      <header
        data-testid="experience-cover-hero"
        style={displayCoverUrl ? { backgroundImage: `url("${displayCoverUrl}")` } : undefined}
        className={cn(
          'relative isolate mt-3 min-h-[360px] overflow-hidden rounded-xl bg-[hsl(var(--memory-panel-elevated))] bg-cover bg-center ring-1 ring-inset ring-[hsl(var(--memory-border)/0.22)]',
          !isInline && 'shadow-[0_14px_42px_hsl(var(--memory-title)/0.055)]'
        )}
      >
        {!displayCoverUrl ? (
          <div className="absolute inset-0 bg-[linear-gradient(135deg,hsl(var(--memory-panel-elevated)),hsl(var(--memory-accent-soft)/0.42))]" />
        ) : null}
        <div className="absolute inset-0 bg-[linear-gradient(90deg,hsl(var(--memory-panel-elevated)/0.94)_0%,hsl(var(--memory-panel-elevated)/0.82)_42%,hsl(var(--memory-panel-elevated)/0.18)_100%)]" />
        <div className="absolute inset-x-0 bottom-0 h-2/3 bg-[linear-gradient(0deg,hsl(var(--memory-panel-elevated)/0.88),transparent)]" />

        <div className="relative z-10 flex min-h-[360px] max-w-3xl flex-col justify-center px-6 py-7 md:px-10 md:py-8">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
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

          <h2 className={cn(
            'mt-5 max-w-3xl break-words font-semibold leading-tight text-[hsl(var(--memory-title))]',
            isInline ? 'text-2xl' : 'text-3xl md:text-[2.28rem]'
          )}>
            {title}
          </h2>

          <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-[hsl(var(--memory-muted))]">
            <span className="inline-flex items-center gap-1">
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              {t('memory.episodes.episodeCount', { count: experience.source_episode_count ?? 0 })}
            </span>
            <span>{t('memory.episodes.eventCount', { count: experience.source_event_count ?? 0 })}</span>
          </div>

          <div className="mt-7 max-w-2xl border-l-2 border-[hsl(var(--memory-accent)/0.38)] bg-[hsl(var(--memory-panel-elevated)/0.5)] px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
              <Quote className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
              {t('memory.episodes.sections.recap')}
            </div>
            <p className="mt-3 whitespace-pre-wrap break-words text-base leading-8 text-[hsl(var(--memory-body))]">
              {readableRecap || t('memory.episodes.noRecap')}
            </p>
          </div>

        </div>
      </header>

      <main className="mt-4 min-w-0 space-y-5">
        {hasRelatedObjects ? (
          <RelatedObjectsPanel
            entities={entityLabels}
            places={placeLabels}
            topics={topicLabels}
          />
        ) : null}
        {detailLoading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
        <SourceEpisodeList episodes={sourceEpisodes} eventsByEpisode={eventsByEpisode} />
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

function SourceEpisodeList({
  episodes,
  eventsByEpisode,
}: {
  episodes: L2EpisodeWithSummary[];
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>;
}) {
  const { t, i18n } = useTranslation('app');
  return (
    <section data-testid="episode-event-stream">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <Layers className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.sourceEpisodes')}
      </h3>
      <div data-testid="experience-source-episodes" className="mt-3 grid gap-3">
        {episodes.length === 0 ? (
          <div className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">
            {t('memory.episodes.noSourceEpisodes')}
          </div>
        ) : episodes.map((episode, index) => {
          const title = getReadableSourceEpisodeTitle(
            episode,
            index,
            t('memory.episodes.sourceEpisodeFallback', { index: index + 1 }),
            eventsByEpisode
          );
          const rawSummary = getReadableSourceEpisodeSummary(episode, eventsByEpisode);
          const summary = rawSummary === title ? '' : rawSummary;
          const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
          const episodeEvents = eventsByEpisode.get(episode.episode_id) ?? [];
          return (
            <article key={episode.episode_id} className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.74)] px-5 py-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h4 className="break-words text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">{title}</h4>
                  {summary ? (
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-[hsl(var(--memory-body))]">{summary}</p>
                  ) : null}
                </div>
                <div className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">
                  {range}
                </div>
              </div>
              <SourceEpisodeEventTrail events={episodeEvents} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SourceEpisodeEventTrail({ events }: { events: L2EpisodeEventPreview[] }) {
  const { t, i18n } = useTranslation('app');
  if (events.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 border-t border-[hsl(var(--memory-divider)/0.58)] pt-4">
      <div className="flex items-center gap-2 text-xs font-semibold text-[hsl(var(--memory-muted))]">
        <GitMerge className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.whatHappened')}
      </div>
      <div className="mt-3 grid gap-2">
        {events.map((event) => {
          const time = formatEventTime(event.timestamp ?? event.added_at, i18n.language);
          const preview = String(event.content_preview || '').trim();
          const source = formatSourceLabel(event.source);
          return (
            <article
              key={`${event.episode_id}-${event.event_id}`}
              className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.5)] px-3 py-2"
            >
              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">
                  {preview || t('memory.episodes.eventPreviewUnavailable')}
                </p>
                {time ? <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{time}</span> : null}
              </div>
              {source ? (
                <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{source}</div>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function RelatedObjectsPanel({
  entities,
  places,
  topics,
}: {
  entities: string[];
  places: string[];
  topics: string[];
}) {
  const { t } = useTranslation('app');
  return (
    <section className="rounded-lg border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.5)] px-5 py-4">
      <div className="grid gap-4 md:grid-cols-3">
        <TagGroup
          icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.entities')}
          values={entities}
        />
        <TagGroup
          icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.places')}
          values={places}
        />
        <TagGroup
          icon={<Tags className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.topics')}
          values={topics}
        />
      </div>
    </section>
  );
}

function TagGroup({ icon, title, values }: { icon: ReactNode; title: string; values: string[] }) {
  const { t } = useTranslation('app');
  return (
    <section className="min-w-0">
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
