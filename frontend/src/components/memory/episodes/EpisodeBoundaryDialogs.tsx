import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type L2EpisodeCandidate,
  type L2EpisodeEventPreview,
  type L2EpisodeReviewDetail,
  type L2EpisodeSplitPreview,
} from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface BoundaryDialogProps {
  episodeId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddEventDialog({
  episodeId,
  open,
  onOpenChange,
  onEpisodeUpdated,
}: BoundaryDialogProps & {
  onEpisodeUpdated: (episode: L2EpisodeReviewDetail) => void;
}) {
  const { t } = useTranslation('app');
  const [items, setItems] = useState<L2EpisodeEventPreview[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedIds(new Set());
    void memoryApi.listEpisodeEventCandidates(episodeId).then((payload) => setItems(payload.items));
  }, [episodeId, open]);

  const toggle = (eventId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  };

  const addSelected = async () => {
    const eventIds = Array.from(selectedIds);
    if (eventIds.length === 0) {
      return;
    }
    setSaving(true);
    try {
      const updated = await memoryApi.addEpisodeEvents(episodeId, eventIds);
      onEpisodeUpdated(updated);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('memory.episodes.dialogs.addEventTitle')}</DialogTitle>
          <DialogDescription>{t('memory.episodes.dialogs.addEventDescription')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[420px] space-y-2 overflow-y-auto px-6 pb-3">
          {items.length === 0 ? (
            <div className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">
              {t('memory.episodes.empty.noEventCandidates')}
            </div>
          ) : items.map((item) => {
            const label = String(item.content_preview || item.event_id);
            return (
              <label key={item.event_id} className="flex cursor-pointer items-start gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3">
                <input
                  type="checkbox"
                  checked={selectedIds.has(item.event_id)}
                  onChange={() => toggle(item.event_id)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="block whitespace-pre-wrap break-words text-sm text-[hsl(var(--memory-body))]">{label}</span>
                  <span className="mt-1 block break-all font-mono text-xs text-[hsl(var(--memory-muted))]">{item.event_id}</span>
                </span>
              </label>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void addSelected()} disabled={saving || selectedIds.size === 0}>
            {saving ? t('common.saving') : t('memory.episodes.actions.addSelectedEvents')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MergeEpisodeDialog({
  episodeId,
  open,
  onOpenChange,
  onEpisodeUpdated,
}: BoundaryDialogProps & {
  onEpisodeUpdated: (episode: L2EpisodeReviewDetail) => void;
}) {
  const { t } = useTranslation('app');
  const [items, setItems] = useState<L2EpisodeCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedId(null);
    void memoryApi.listEpisodeMergeCandidates(episodeId).then((payload) => setItems(payload.items));
  }, [episodeId, open]);

  const mergeSelected = async () => {
    if (!selectedId) {
      return;
    }
    setSaving(true);
    try {
      const updated = await memoryApi.mergeEpisodes(episodeId, selectedId);
      onEpisodeUpdated(updated);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('memory.episodes.dialogs.mergeEpisodeTitle')}</DialogTitle>
          <DialogDescription>{t('memory.episodes.dialogs.mergeEpisodeDescription')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[420px] space-y-2 overflow-y-auto px-6 pb-3">
          {items.length === 0 ? (
            <div className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">
              {t('memory.episodes.empty.noMergeCandidates')}
            </div>
          ) : items.map((item) => {
            const title = item.display_title || item.user_label || item.episode_summary?.label || item.label || item.episode_id;
            const description = item.display_description || item.episode_summary?.content || item.summary || '';
            return (
              <label key={item.episode_id} className="flex cursor-pointer items-start gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3">
                <input
                  type="radio"
                  name="episode-merge-candidate"
                  checked={selectedId === item.episode_id}
                  onChange={() => setSelectedId(item.episode_id)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="block break-words text-sm font-medium text-[hsl(var(--memory-title))]">{title}</span>
                  {description ? <span className="mt-1 block line-clamp-2 text-sm text-[hsl(var(--memory-muted))]">{description}</span> : null}
                </span>
              </label>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void mergeSelected()} disabled={saving || !selectedId}>
            {saving ? t('common.saving') : t('memory.episodes.actions.mergeSelectedEpisode')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SplitEpisodeDialog({
  episodeId,
  events,
  open,
  onOpenChange,
  onEpisodeSplit,
}: BoundaryDialogProps & {
  events: L2EpisodeEventPreview[];
  onEpisodeSplit: (episodes: L2EpisodeReviewDetail[]) => void;
}) {
  const { t } = useTranslation('app');
  const [breakAfterEventId, setBreakAfterEventId] = useState<string | null>(null);
  const [preview, setPreview] = useState<L2EpisodeSplitPreview | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      setBreakAfterEventId(null);
      setPreview(null);
    }
  }, [open]);

  const chooseBreakpoint = (eventId: string) => {
    setBreakAfterEventId(eventId);
    void memoryApi.previewEpisodeSplit(episodeId, eventId).then((payload) => setPreview(payload));
  };

  const splitNow = async () => {
    if (!breakAfterEventId) {
      return;
    }
    setSaving(true);
    try {
      const result = await memoryApi.splitEpisode(episodeId, breakAfterEventId);
      onEpisodeSplit(result.items);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('memory.episodes.dialogs.splitEpisodeTitle')}</DialogTitle>
          <DialogDescription>{t('memory.episodes.dialogs.splitEpisodeDescription')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[420px] space-y-2 overflow-y-auto px-6 pb-3">
          {events.slice(0, -1).map((event) => {
            const label = String(event.content_preview || event.event_id);
            return (
              <label key={event.event_id} className="flex cursor-pointer items-start gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3">
                <input
                  type="radio"
                  name="episode-split-breakpoint"
                  checked={breakAfterEventId === event.event_id}
                  onChange={() => chooseBreakpoint(event.event_id)}
                  className="mt-1"
                />
                <span className="min-w-0 text-sm text-[hsl(var(--memory-body))]">{label}</span>
              </label>
            );
          })}
          {preview ? (
            <div className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">
              {preview.left.event_count} / {preview.right.event_count}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void splitNow()} disabled={saving || !breakAfterEventId}>
            {saving ? t('common.saving') : t('memory.episodes.actions.splitNow')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
