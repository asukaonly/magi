import { useState } from 'react';
import { MapPin, Tags, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { memoryApi, type L2Episode, type L2EpisodeEventPreview, type L2EpisodeReviewDetail, type L2EpisodeWithSummary } from '@/api/modules/memory';
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
import { formatEpisodeTimeRange } from './EpisodeRow';
import EpisodeEventList from './EpisodeEventList';
import EpisodeNarrative, { getEpisodeReviewDescription } from './EpisodeNarrative';
import { AddEventDialog, MergeEpisodeDialog, SplitEpisodeDialog } from './EpisodeBoundaryDialogs';

type EpisodeReviewLike = L2Episode | L2EpisodeWithSummary | L2EpisodeReviewDetail;

const normalizeList = (items: string[] | null | undefined): string[] => (
  Array.isArray(items) ? items.filter((item) => Boolean(item && item.trim())) : []
);

const MEMORY_INFO_PANEL_CLASS = 'rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]';

export function EpisodeDetail({
  episode,
  title,
  detailLoading,
  onRenameTitle,
  onEditDescription,
  onRegenerate,
  onEpisodeUpdated,
  onEpisodeSplit,
}: {
  episode: EpisodeReviewLike;
  title: string;
  detailLoading: boolean;
  onRenameTitle: (title: string) => Promise<void>;
  onEditDescription: (description: string) => Promise<void>;
  onRegenerate: () => Promise<void>;
  onEpisodeUpdated: (episode: L2EpisodeReviewDetail) => void;
  onEpisodeSplit: (episodes: L2EpisodeReviewDetail[]) => void;
}) {
  const { t, i18n } = useTranslation('app');
  const events = ('events' in episode ? episode.events : []) as L2EpisodeEventPreview[];
  const description = getEpisodeReviewDescription(episode);
  const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${episode.episode_type || 'activity'}`, {
    defaultValue: episode.episode_type || '',
  });
  const [renameOpen, setRenameOpen] = useState(false);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [splitOpen, setSplitOpen] = useState(false);
  const [removeMode, setRemoveMode] = useState(false);
  const [selectedRemoveIds, setSelectedRemoveIds] = useState<Set<string>>(new Set());
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
    if (episode.user_note) {
      setRegenerateOpen(true);
      return;
    }
    void runRegenerate();
  };

  const toggleRemoveEvent = (eventId: string) => {
    setSelectedRemoveIds((prev) => {
      const next = new Set(prev);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  };

  const removeSelectedEvents = async () => {
    const eventIds = Array.from(selectedRemoveIds);
    if (eventIds.length === 0) {
      return;
    }
    setSaving(true);
    try {
      const updated = await memoryApi.removeEpisodeEvents(episode.episode_id, eventIds);
      onEpisodeUpdated(updated);
      setSelectedRemoveIds(new Set());
      setRemoveMode(false);
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
              {episode.user_pinned ? (
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
            <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>{t('memory.episodes.actions.addEvent')}</Button>
            <Button variant="outline" size="sm" onClick={() => setRemoveMode((value) => !value)}>{t('memory.episodes.actions.removeEvent')}</Button>
            <Button variant="outline" size="sm" onClick={() => setMergeOpen(true)}>{t('memory.episodes.actions.mergeEpisode')}</Button>
            <Button variant="outline" size="sm" onClick={() => setSplitOpen(true)}>{t('memory.episodes.actions.splitEpisode')}</Button>
          </div>
        </div>
      </header>

      <div className="space-y-5 px-5 py-5">
        {detailLoading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
        <EpisodeNarrative episode={episode} />
        <div className="grid gap-3 md:grid-cols-3">
          <TagGroup
            icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.people')}
            values={normalizeList(episode.primary_entity_ids)}
          />
          <TagGroup
            icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.places')}
            values={normalizeList(episode.primary_place_ids)}
          />
          <TagGroup
            icon={<Tags className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.topics')}
            values={normalizeList(episode.primary_topic_keys)}
          />
        </div>
        {removeMode ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => {
              setSelectedRemoveIds(new Set());
              setRemoveMode(false);
            }}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void removeSelectedEvents()} disabled={saving || selectedRemoveIds.size === 0}>
              {saving ? t('common.saving') : t('memory.episodes.actions.removeSelectedEvents')}
            </Button>
          </div>
        ) : null}
        <EpisodeEventList
          events={events}
          selectable={removeMode}
          selectedEventIds={selectedRemoveIds}
          onToggleEvent={toggleRemoveEvent}
        />
      </div>

      <AddEventDialog
        episodeId={episode.episode_id}
        open={addOpen}
        onOpenChange={setAddOpen}
        onEpisodeUpdated={onEpisodeUpdated}
      />
      <MergeEpisodeDialog
        episodeId={episode.episode_id}
        open={mergeOpen}
        onOpenChange={setMergeOpen}
        onEpisodeUpdated={onEpisodeUpdated}
      />
      <SplitEpisodeDialog
        episodeId={episode.episode_id}
        events={events}
        open={splitOpen}
        onOpenChange={setSplitOpen}
        onEpisodeSplit={onEpisodeSplit}
      />

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
    </div>
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

export default EpisodeDetail;
