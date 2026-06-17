import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Check, Edit3, GitMerge, MapPin, Sparkles, Tags, UserRound, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type L2Episode,
  type L2EpisodeDetail,
  type L2EpisodeInference,
  type L2EpisodeWithSummary,
} from '@/api/modules/memory';
import EpisodeRow, { formatEpisodeTimeRange, getEpisodeDisplayTitle } from '@/components/memory/episodes/EpisodeRow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';

interface CorrectionDraft {
  user_label: string;
  user_note: string;
  user_pinned: boolean;
}

const createDraft = (episode: L2Episode | null): CorrectionDraft => ({
  user_label: episode?.user_label ?? '',
  user_note: episode?.user_note ?? '',
  user_pinned: Boolean(episode?.user_pinned),
});

const isNonEmpty = (value: string | null | undefined): value is string => Boolean(value && value.trim());

const normalizeList = (items: string[] | null | undefined): string[] => (
  Array.isArray(items) ? items.filter((item) => isNonEmpty(item)) : []
);

const formatConfidence = (value: number | null | undefined, locale: string): string => (
  typeof value === 'number'
    ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(value)
    : ''
);

const mergeEpisodeIntoList = (
  items: L2EpisodeWithSummary[],
  updated: L2Episode,
): L2EpisodeWithSummary[] => items.map((item) => (
  item.episode_id === updated.episode_id ? { ...item, ...updated } : item
));

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2EpisodeWithSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<L2EpisodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState<CorrectionDraft>(() => createDraft(null));
  const [saving, setSaving] = useState(false);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ limit: 100, offset: 0 });
      setEpisodes(payload.items);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.episode_id === current)) {
          return current;
        }
        return payload.items[0]?.episode_id ?? null;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setDetailLoading(true);
    void memoryApi.getEpisode(selectedId)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectedListEpisode = useMemo(
    () => episodes.find((episode) => episode.episode_id === selectedId) ?? null,
    [episodes, selectedId]
  );
  const selectedEpisode = detail ?? selectedListEpisode;
  const selectedTitle = selectedEpisode
    ? getEpisodeDisplayTitle(selectedEpisode, t('memory.episodes.awaitingLabel'))
    : '';

  const openEdit = () => {
    setDraft(createDraft(selectedEpisode));
    setEditOpen(true);
  };

  const saveCorrections = async () => {
    if (!selectedEpisode) {
      return;
    }
    setSaving(true);
    try {
      const updated = await memoryApi.annotateEpisode(selectedEpisode.episode_id, {
        user_label: draft.user_label,
        user_note: draft.user_note,
        user_pinned: draft.user_pinned,
      });
      setEpisodes((prev) => mergeEpisodeIntoList(prev, updated));
      setDetail((prev) => (prev && prev.episode_id === updated.episode_id ? { ...prev, ...updated } : prev));
      setEditOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const submitFeedback = async (assertionId: string, feedback: 'confirmed' | 'rejected') => {
    setFeedbackSubmitting((prev) => ({ ...prev, [assertionId]: true }));
    try {
      const updated = await memoryApi.submitAssertionFeedback(assertionId, feedback);
      setDetail((prev) => {
        if (!prev) {
          return prev;
        }
        return {
          ...prev,
          inferred: prev.inferred.map((item) => (
            item.assertion_id === assertionId
              ? { ...item, user_feedback: updated.user_feedback ?? feedback }
              : item
          )),
        };
      });
    } finally {
      setFeedbackSubmitting((prev) => ({ ...prev, [assertionId]: false }));
    }
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      contentClassName="min-h-0"
    >
      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : episodes.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
        <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(280px,420px)_minmax(0,1fr)]">
          <section className="min-w-0 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.episodes.sections.list')}
              </h2>
              <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-muted))]">
                {t('memory.episodes.count', { count: episodes.length })}
              </Badge>
            </div>
            <div className="space-y-2">
              {episodes.map((episode) => (
                <EpisodeRow
                  key={episode.episode_id}
                  episode={episode}
                  selected={episode.episode_id === selectedId}
                  onOpen={() => setSelectedId(episode.episode_id)}
                />
              ))}
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.7)]">
            {selectedEpisode ? (
              <EpisodeDetail
                episode={selectedEpisode}
                title={selectedTitle}
                detailLoading={detailLoading}
                onEdit={openEdit}
                onFeedback={submitFeedback}
                feedbackSubmitting={feedbackSubmitting}
              />
            ) : (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.detailEmptyTitle')}</div>
                <p className="mt-1 text-sm">{t('memory.episodes.detailEmptyBody')}</p>
              </div>
            )}
          </section>
        </div>
      )}

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('memory.episodes.actions.edit')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 px-6 pb-2">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.label')}</span>
              <Input
                value={draft.user_label}
                onChange={(event) => setDraft((prev) => ({ ...prev, user_label: event.target.value }))}
                className="border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))]"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.note')}</span>
              <Textarea
                value={draft.user_note}
                onChange={(event) => setDraft((prev) => ({ ...prev, user_note: event.target.value }))}
                className="min-h-[120px] border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))]"
              />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-3 py-2">
              <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.pinned')}</span>
              <Switch
                aria-label={t('memory.episodes.fields.pinned')}
                checked={draft.user_pinned}
                onCheckedChange={(checked) => setDraft((prev) => ({ ...prev, user_pinned: checked }))}
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void saveCorrections()} disabled={saving}>
              {saving ? t('common.saving') : t('memory.episodes.actions.saveCorrections')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </MemoryPageFrame>
  );
};

const EpisodeDetail = ({
  episode,
  title,
  detailLoading,
  onEdit,
  onFeedback,
  feedbackSubmitting,
}: {
  episode: L2Episode | L2EpisodeDetail;
  title: string;
  detailLoading: boolean;
  onEdit: () => void;
  onFeedback: (assertionId: string, feedback: 'confirmed' | 'rejected') => void;
  feedbackSubmitting: Record<string, boolean>;
}) => {
  const { t, i18n } = useTranslation('app');
  const events = 'events' in episode ? episode.events : [];
  const inferred = 'inferred' in episode ? episode.inferred : [];
  const narrative = String(episode.slice_narrative || '').trim();
  const summary = String(episode.summary || '').trim();
  const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${episode.episode_type || 'activity'}`, {
    defaultValue: episode.episode_type || '',
  });

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
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Edit3 className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.actions.edit')}
          </Button>
        </div>
      </header>

      <div className="space-y-5 px-5 py-5">
        {detailLoading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}

        <section>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
            <Sparkles className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {t('memory.episodes.sections.narrative')}
          </h3>
          <div className="mt-3 space-y-3 text-sm leading-6 text-[hsl(var(--memory-body))]">
            <p className="whitespace-pre-wrap break-words">{narrative || t('memory.episodes.noNarrative')}</p>
            <p className="whitespace-pre-wrap break-words text-[hsl(var(--memory-muted))]">
              {summary || t('memory.episodes.noSummary')}
            </p>
          </div>
        </section>

        {episode.user_note ? (
          <section className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.52)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.sections.userNotes')}</h3>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">{episode.user_note}</p>
          </section>
        ) : null}

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

        <section>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
            <GitMerge className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {t('memory.episodes.sections.eventStream')}
          </h3>
          <div data-testid="episode-event-stream" className="mt-3 overflow-hidden rounded-xl border border-[hsl(var(--memory-border)/0.52)]">
            {events.length === 0 ? (
              <div className="px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noEvents')}</div>
            ) : events.map((event) => (
              <div key={`${event.episode_id}-${event.event_id}`} className="flex flex-col gap-1 border-t border-[hsl(var(--memory-divider)/0.54)] px-4 py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="break-all font-mono text-xs text-[hsl(var(--memory-title))]">{event.event_id}</div>
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                    {t(`memory.episodes.eventRole.${event.membership_role}`, { defaultValue: event.membership_role })}
                  </div>
                </div>
                <div className="text-xs text-[hsl(var(--memory-muted))]">
                  {formatConfidence(event.membership_confidence, i18n.language)}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.sections.inferred')}</h3>
          <div className="mt-3 space-y-3">
            {inferred.length === 0 ? (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.noInferred')}</div>
            ) : inferred.map((item) => (
              <InferenceCard
                key={item.assertion_id}
                item={item}
                submitting={Boolean(feedbackSubmitting[item.assertion_id])}
                onFeedback={onFeedback}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

const TagGroup = ({ icon, title, values }: { icon: ReactNode; title: string; values: string[] }) => {
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
};

const InferenceCard = ({
  item,
  submitting,
  onFeedback,
}: {
  item: L2EpisodeInference;
  submitting: boolean;
  onFeedback: (assertionId: string, feedback: 'confirmed' | 'rejected') => void;
}) => {
  const { t, i18n } = useTranslation('app');
  const feedbackLabel = item.user_feedback === 'confirmed'
    ? t('memory.episodes.feedback.confirmed')
    : item.user_feedback === 'rejected'
      ? t('memory.episodes.feedback.rejected')
      : t('memory.episodes.feedback.pending');
  const confidence = formatConfidence(item.confidence_score, i18n.language);
  const body = item.natural_summary || `${item.trait_name}: ${item.trait_value}`;

  return (
    <article className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.46)] px-4 py-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.78)] text-[hsl(var(--memory-body))]">
              {item.trait_family || item.trait_name}
            </Badge>
            <span className="text-xs text-[hsl(var(--memory-muted))]">{feedbackLabel}</span>
            {confidence ? <span className="text-xs text-[hsl(var(--memory-muted))]">{confidence}</span> : null}
          </div>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p>
          <div className="mt-2 break-all font-mono text-xs text-[hsl(var(--memory-muted))]">{item.entity_id}</div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={submitting}
            onClick={() => onFeedback(item.assertion_id, 'confirmed')}
            aria-label={t('memory.episodes.actions.confirmImpression')}
          >
            <Check className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.feedback.confirmed')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={submitting}
            onClick={() => onFeedback(item.assertion_id, 'rejected')}
            aria-label={t('memory.episodes.actions.rejectImpression')}
          >
            <X className="h-4 w-4" aria-hidden="true" />
            {t('memory.episodes.feedback.rejected')}
          </Button>
        </div>
      </div>
    </article>
  );
};

export default MemoryEpisodesPage;
