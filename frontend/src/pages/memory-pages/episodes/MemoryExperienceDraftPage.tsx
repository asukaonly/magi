import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, CalendarDays } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  memoryApi,
  type ExperienceDraft,
  type ExperienceDraftChapter,
  type ExperienceDraftEvidence,
  type ExperienceDraftUpdatePayload,
} from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { formatEpisodeTimeRange } from '@/components/memory/episodes/EpisodeRow';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from '../MemoryPageFrame';

const toDateValue = (value?: number | null) => {
  if (!value) return '';
  const date = new Date(value * 1000);
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localDate.toISOString().slice(0, 10);
};

const fromDateValue = (value: string, boundary: 'start' | 'end') => {
  if (!value) return undefined;
  const suffix = boundary === 'start' ? 'T00:00:00' : 'T23:59:59';
  return new Date(`${value}${suffix}`).getTime() / 1000;
};

const evidenceRefKey = (refType: string, refId: string) => `${refType}\u0000${refId}`;

const chapterRefKeys = (chapter: ExperienceDraftChapter): string[] => [
  ...chapter.episode_ids.map((refId) => evidenceRefKey('episode', refId)),
  ...chapter.event_ids.map((refId) => evidenceRefKey('event', refId)),
];

const dedupeEvidence = (
  evidence: ExperienceDraftEvidence[],
  blockedKeys: Set<string>,
): ExperienceDraftEvidence[] => {
  const seen = new Set(blockedKeys);
  return evidence.filter((item) => {
    const key = evidenceRefKey(item.ref_type, item.ref_id);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

const normalizeDraftEvidence = (draft: ExperienceDraft): { draft: ExperienceDraft; changed: boolean } => {
  const selectedKeys = new Set(draft.chapters.flatMap(chapterRefKeys));
  const possibleEvidence = dedupeEvidence(draft.possible_evidence, selectedKeys);
  const possibleKeys = new Set(possibleEvidence.map((item) => evidenceRefKey(item.ref_type, item.ref_id)));
  const excludedEvidence = dedupeEvidence(
    draft.excluded_evidence,
    new Set([...selectedKeys, ...possibleKeys]),
  );
  const changed = possibleEvidence.length !== draft.possible_evidence.length
    || possibleEvidence.some((item, index) => item !== draft.possible_evidence[index])
    || excludedEvidence.length !== draft.excluded_evidence.length
    || excludedEvidence.some((item, index) => item !== draft.excluded_evidence[index]);
  return {
    draft: changed ? {
      ...draft,
      possible_evidence: possibleEvidence,
      excluded_evidence: excludedEvidence,
    } : draft,
    changed,
  };
};

const toUpdatePayload = (draft: ExperienceDraft): ExperienceDraftUpdatePayload => ({
  title: draft.title,
  one_sentence_review: draft.one_sentence_review,
  time_start: draft.time_start,
  time_end: draft.time_end,
  chapters: draft.chapters,
  possible_evidence: draft.possible_evidence,
  excluded_evidence: draft.excluded_evidence,
});

interface PossibleSegment {
  key: string;
  evidence: ExperienceDraftEvidence;
}

const getPossibleSegments = (evidence: ExperienceDraftEvidence[]): PossibleSegment[] => {
  const segments = new Map<string, PossibleSegment>();
  evidence.forEach((item) => {
    const key = item.restore_chapter
      ? `chapter:${item.restore_chapter.chapter_id}`
      : `evidence:${evidenceRefKey(item.ref_type, item.ref_id)}`;
    if (!segments.has(key)) segments.set(key, { key, evidence: item });
  });
  return [...segments.values()];
};

interface PendingFocus {
  section: 'included' | 'possible';
  key: string;
  announcement: string;
}

export const MemoryExperienceDraftPage = () => {
  const { t, i18n } = useTranslation('app');
  const { draftId } = useParams<{ draftId: string }>();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<ExperienceDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [possibleOpen, setPossibleOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const draftRef = useRef<ExperienceDraft | null>(null);
  const revisionRef = useRef(0);
  const savedRevisionRef = useRef(0);
  const queuedRevisionRef = useRef(0);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const pendingSaveCountRef = useRef(0);
  const pendingFocusRef = useRef<PendingFocus | null>(null);
  const chapterCheckboxRefs = useRef(new Map<string, HTMLInputElement>());
  const possibleCheckboxRefs = useRef(new Map<string, HTMLInputElement>());

  useEffect(() => {
    if (!draftId) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    let cancelled = false;
    void memoryApi.getExperienceDraft(draftId)
      .then((payload) => {
        if (!cancelled) {
          const normalized = normalizeDraftEvidence(payload);
          draftRef.current = normalized.draft;
          revisionRef.current = normalized.changed ? 1 : 0;
          savedRevisionRef.current = 0;
          queuedRevisionRef.current = 0;
          saveQueueRef.current = Promise.resolve();
          pendingSaveCountRef.current = 0;
          setPossibleOpen(false);
          setDraft(normalized.draft);
        }
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [draftId]);

  const enqueueSave = useCallback((snapshot: ExperienceDraft, revision: number): Promise<void> => {
    if (!draftId) return Promise.resolve();
    if (revision <= queuedRevisionRef.current) return saveQueueRef.current;

    queuedRevisionRef.current = revision;
    pendingSaveCountRef.current += 1;
    setSaving(true);
    const priorSave = saveQueueRef.current.catch(() => undefined);
    const nextSave = priorSave.then(async () => {
      setSaveFailed(false);
      try {
        await memoryApi.updateExperienceDraft(draftId, toUpdatePayload(snapshot));
        savedRevisionRef.current = Math.max(savedRevisionRef.current, revision);
      } catch (error) {
        if (queuedRevisionRef.current === revision) {
          queuedRevisionRef.current = savedRevisionRef.current;
        }
        setSaveFailed(true);
        throw error;
      } finally {
        pendingSaveCountRef.current -= 1;
        if (pendingSaveCountRef.current === 0) setSaving(false);
      }
    });
    saveQueueRef.current = nextSave;
    return nextSave;
  }, [draftId]);

  useEffect(() => {
    if (!draftId || !draft) return;
    const revision = revisionRef.current;
    if (revision <= savedRevisionRef.current || revision <= queuedRevisionRef.current) return;
    const timer = window.setTimeout(() => {
      void enqueueSave(draft, revision).catch(() => undefined);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, draftId, enqueueSave]);

  const changeDraft = useCallback((mutate: (current: ExperienceDraft) => ExperienceDraft) => {
    setDraft((current) => {
      if (!current) return current;
      const normalized = normalizeDraftEvidence(mutate(current)).draft;
      revisionRef.current += 1;
      draftRef.current = normalized;
      return normalized;
    });
  }, []);

  useEffect(() => {
    const pendingFocus = pendingFocusRef.current;
    if (!pendingFocus) return;
    const target = pendingFocus.section === 'included'
      ? chapterCheckboxRefs.current.get(pendingFocus.key)
      : possibleCheckboxRefs.current.get(pendingFocus.key);
    if (!target) return;
    pendingFocusRef.current = null;
    target.focus();
    setAnnouncement(pendingFocus.announcement);
  }, [draft, possibleOpen]);

  const removeChapter = (chapter: ExperienceDraftChapter, chapterIndex: number) => {
    const restoreChapter = {
      chapter_id: chapter.chapter_id,
      chapter_index: chapterIndex,
      episode_ids: chapter.episode_ids,
      event_ids: chapter.event_ids,
    };
    const possibleEvidence: ExperienceDraftEvidence[] = [
      ...chapter.episode_ids.map((refId) => ({
        ref_type: 'episode',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
        restore_chapter: restoreChapter,
      })),
      ...chapter.event_ids.map((refId) => ({
        ref_type: 'event',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
        restore_chapter: restoreChapter,
      })),
    ];
    const movedKeys = new Set(possibleEvidence.map((item) => evidenceRefKey(item.ref_type, item.ref_id)));
    pendingFocusRef.current = {
      section: 'possible',
      key: `chapter:${chapter.chapter_id}`,
      announcement: `${t('memory.episodes.draft.possible')}: ${chapter.title}`,
    };
    setPossibleOpen(true);
    changeDraft((current) => {
      return {
        ...current,
        chapters: current.chapters.filter((item) => item.chapter_id !== chapter.chapter_id),
        possible_evidence: [
          ...current.possible_evidence.filter((item) => !movedKeys.has(evidenceRefKey(item.ref_type, item.ref_id))),
          ...possibleEvidence,
        ],
      };
    });
  };

  const addPossibleEvidence = (segment: PossibleSegment) => {
    const { evidence } = segment;
    const restoreChapter = evidence.restore_chapter;
    const chapter: ExperienceDraftChapter = {
      chapter_id: restoreChapter?.chapter_id ?? `chapter-${crypto.randomUUID()}`,
      title: evidence.title,
      summary: evidence.summary,
      time_start: evidence.time_start,
      time_end: evidence.time_end,
      episode_ids: restoreChapter?.episode_ids ?? (evidence.ref_type === 'episode' ? [evidence.ref_id] : []),
      event_ids: restoreChapter?.event_ids ?? (evidence.ref_type === 'event' ? [evidence.ref_id] : []),
    };
    pendingFocusRef.current = {
      section: 'included',
      key: chapter.chapter_id,
      announcement: `${t('memory.episodes.draft.chapters')}: ${chapter.title}`,
    };
    changeDraft((current) => {
      const chapters = current.chapters.filter((item) => item.chapter_id !== chapter.chapter_id);
      const chapterIndex = restoreChapter
        ? Math.min(Math.max(restoreChapter.chapter_index, 0), chapters.length)
        : chapters.length;
      chapters.splice(chapterIndex, 0, chapter);
      return {
        ...current,
        chapters,
        possible_evidence: current.possible_evidence.filter((item) => (
          restoreChapter
            ? item.restore_chapter?.chapter_id !== restoreChapter.chapter_id
            : evidenceRefKey(item.ref_type, item.ref_id) !== evidenceRefKey(evidence.ref_type, evidence.ref_id)
        )),
      };
    });
  };

  const flushLatestDraft = useCallback(async () => {
    while (savedRevisionRef.current < revisionRef.current) {
      const latestDraft = draftRef.current;
      if (!latestDraft) return;
      await enqueueSave(latestDraft, revisionRef.current);
    }
  }, [enqueueSave]);

  const createExperience = async () => {
    if (!draftId || !draftRef.current) return;
    setCreating(true);
    try {
      await flushLatestDraft();
      const result = await memoryApi.createExperienceFromDraft(draftId);
      navigate(`/memory/episodes/${result.experience_id}`);
    } finally {
      setCreating(false);
    }
  };

  const possibleSegments = draft ? getPossibleSegments(draft.possible_evidence) : [];

  return (
    <MemoryPageFrame
      title={t('memory.episodes.draft.title')}
      description=""
      hideHeader
      className="max-w-[1040px] gap-4 px-4 pb-8 pt-4"
    >
      <div className="grid min-h-8 grid-cols-[1fr_auto_1fr] items-center gap-3">
        <Button variant="ghost" className="-ml-2 h-8 px-2 text-xs" onClick={() => navigate('/memory/episodes')}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t('memory.episodes.draft.back')}
        </Button>
        <h1 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.draft.title')}</h1>
        <span className="justify-self-end text-xs text-[hsl(var(--memory-muted))]">
          {saving
            ? t('common.saving')
            : saveFailed
              ? t('memory.episodes.draft.saveFailed')
              : t('memory.episodes.draft.autosaved')}
        </span>
      </div>
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {loading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
      {!loading && (notFound || !draft) ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.draft.notFound')}</div>
      ) : null}
      {draft ? (
        <div className="space-y-7">
          <header className="border-b border-[hsl(var(--memory-border)/0.45)] pb-6">
            <Input
              aria-label={t('memory.episodes.fields.title')}
              value={draft.title}
              onChange={(event) => changeDraft((current) => ({ ...current, title: event.target.value }))}
              className="h-auto border-0 bg-transparent px-0 text-3xl font-semibold shadow-none focus-visible:ring-0"
            />
            <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-[hsl(var(--memory-muted))]">
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
              <Input
                type="date"
                aria-label={t('memory.episodes.draft.startDate')}
                value={toDateValue(draft.time_start)}
                onChange={(event) => changeDraft((current) => ({
                  ...current,
                  time_start: fromDateValue(event.target.value, 'start') ?? current.time_start,
                }))}
                className="h-8 w-auto"
              />
              <span>-</span>
              <Input
                type="date"
                aria-label={t('memory.episodes.draft.endDate')}
                value={toDateValue(draft.time_end)}
                onChange={(event) => changeDraft((current) => ({
                  ...current,
                  time_end: fromDateValue(event.target.value, 'end') ?? current.time_end,
                }))}
                className="h-8 w-auto"
              />
            </div>
            <label className="mt-5 block space-y-2">
              <span className="text-sm font-medium">{t('memory.episodes.draft.recap')}</span>
              <Textarea
                value={draft.one_sentence_review}
                onChange={(event) => changeDraft((current) => ({
                  ...current,
                  one_sentence_review: event.target.value,
                }))}
                className="min-h-20 resize-none text-base leading-7"
              />
            </label>
          </header>

          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <BookOpen className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
              <h2 className="text-base font-semibold">{t('memory.episodes.draft.chapters')}</h2>
            </div>
            {draft.chapters.map((chapter, index) => {
              const timeRange = formatEpisodeTimeRange(chapter.time_start, chapter.time_end, i18n.language);
              return (
                <article key={chapter.chapter_id} className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] p-4">
                  <label className="flex cursor-pointer items-start gap-3">
                    <input
                      ref={(node) => {
                        if (node) chapterCheckboxRefs.current.set(chapter.chapter_id, node);
                        else chapterCheckboxRefs.current.delete(chapter.chapter_id);
                      }}
                      type="checkbox"
                      checked
                      aria-label={chapter.title}
                      onChange={(event) => {
                        if (!event.target.checked) removeChapter(chapter, index);
                      }}
                      className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--memory-accent))]"
                    />
                    <span className="pt-0.5 text-xs font-semibold text-[hsl(var(--memory-muted))]">{index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                        <h3 className="break-words font-semibold text-[hsl(var(--memory-title))]">{chapter.title}</h3>
                        {timeRange ? (
                          <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{timeRange}</span>
                        ) : null}
                      </div>
                      {chapter.summary ? (
                        <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{chapter.summary}</p>
                      ) : null}
                    </div>
                  </label>
                </article>
              );
            })}
          </section>

          {possibleSegments.length > 0 ? (
            <details
              open={possibleOpen}
              onToggle={(event) => setPossibleOpen(event.currentTarget.open)}
              className="border-t border-[hsl(var(--memory-border)/0.45)] pt-4"
            >
              <summary
                tabIndex={0}
                className="cursor-pointer text-sm font-semibold"
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' && event.key !== ' ') return;
                  event.preventDefault();
                  setPossibleOpen((open) => !open);
                }}
              >
                {t('memory.episodes.draft.possible')} ({possibleSegments.length})
              </summary>
              <div className="mt-3 space-y-2">
                {possibleSegments.map((segment) => {
                  const { evidence } = segment;
                  const timeRange = formatEpisodeTimeRange(evidence.time_start, evidence.time_end, i18n.language);
                  return (
                    <label key={segment.key} className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
                      <input
                        ref={(node) => {
                          if (node) possibleCheckboxRefs.current.set(segment.key, node);
                          else possibleCheckboxRefs.current.delete(segment.key);
                        }}
                        type="checkbox"
                        checked={false}
                        aria-label={evidence.title}
                        onChange={(event) => {
                          if (event.target.checked) addPossibleEvidence(segment);
                        }}
                        className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--memory-accent))]"
                      />
                      <div className="min-w-0">
                        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                          <div className="font-medium">{evidence.title}</div>
                          {timeRange ? (
                            <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{timeRange}</span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">{evidence.summary}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </details>
          ) : null}

          <div className="flex justify-end border-t border-[hsl(var(--memory-border)/0.45)] pt-5">
            <Button
              onClick={() => { void createExperience(); }}
              disabled={creating || !draft.title.trim() || draft.chapters.length === 0}
            >
              {creating ? t('common.saving') : t('memory.episodes.draft.create')}
            </Button>
          </div>
        </div>
      ) : null}
    </MemoryPageFrame>
  );
};
