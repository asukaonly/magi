import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, CalendarDays } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  memoryApi,
  type ExperienceDraft,
  type ExperienceDraftChapter,
  type ExperienceDraftEvidence,
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
  const dirtyRef = useRef(false);

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
          dirtyRef.current = false;
          setDraft(payload);
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

  useEffect(() => {
    if (!draftId || !draft || !dirtyRef.current) return;
    const timer = window.setTimeout(() => {
      setSaving(true);
      setSaveFailed(false);
      dirtyRef.current = false;
      void memoryApi.updateExperienceDraft(draftId, {
        title: draft.title,
        one_sentence_review: draft.one_sentence_review,
        time_start: draft.time_start,
        time_end: draft.time_end,
        chapters: draft.chapters,
        possible_evidence: draft.possible_evidence,
        excluded_evidence: draft.excluded_evidence,
      }).catch(() => {
        dirtyRef.current = true;
        setSaveFailed(true);
      }).finally(() => setSaving(false));
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, draftId]);

  const changeDraft = useCallback((mutate: (current: ExperienceDraft) => ExperienceDraft) => {
    dirtyRef.current = true;
    setDraft((current) => current ? mutate(current) : current);
  }, []);

  const removeChapter = (chapter: ExperienceDraftChapter) => {
    const possibleEvidence: ExperienceDraftEvidence[] = [
      ...chapter.episode_ids.map((refId) => ({
        ref_type: 'episode',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
      })),
      ...chapter.event_ids.map((refId) => ({
        ref_type: 'event',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
      })),
    ];
    changeDraft((current) => {
      const newEvidence = possibleEvidence.filter((candidate) => (
        !current.possible_evidence.some((existing) => (
          existing.ref_type === candidate.ref_type && existing.ref_id === candidate.ref_id
        ))
      ));
      return {
        ...current,
        chapters: current.chapters.filter((item) => item.chapter_id !== chapter.chapter_id),
        possible_evidence: [...current.possible_evidence, ...newEvidence],
      };
    });
  };

  const addPossibleEvidence = (evidence: ExperienceDraftEvidence) => {
    const chapter: ExperienceDraftChapter = {
      chapter_id: `chapter-${crypto.randomUUID()}`,
      title: evidence.title,
      summary: evidence.summary,
      time_start: evidence.time_start,
      time_end: evidence.time_end,
      episode_ids: evidence.ref_type === 'episode' ? [evidence.ref_id] : [],
      event_ids: evidence.ref_type === 'event' ? [evidence.ref_id] : [],
    };
    changeDraft((current) => ({
      ...current,
      chapters: [...current.chapters, chapter],
      possible_evidence: current.possible_evidence.filter((item) => (
        item.ref_type !== evidence.ref_type || item.ref_id !== evidence.ref_id
      )),
    }));
  };

  const createExperience = async () => {
    if (!draftId || !draft) return;
    setCreating(true);
    try {
      if (dirtyRef.current) {
        dirtyRef.current = false;
        await memoryApi.updateExperienceDraft(draftId, {
          title: draft.title,
          one_sentence_review: draft.one_sentence_review,
          time_start: draft.time_start,
          time_end: draft.time_end,
          chapters: draft.chapters,
          possible_evidence: draft.possible_evidence,
          excluded_evidence: draft.excluded_evidence,
        });
      }
      const result = await memoryApi.createExperienceFromDraft(draftId);
      navigate(`/memory/episodes/${result.experience_id}`);
    } finally {
      setCreating(false);
    }
  };

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
                      type="checkbox"
                      checked
                      aria-label={chapter.title}
                      onChange={(event) => {
                        if (!event.target.checked) removeChapter(chapter);
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

          {draft.possible_evidence.length > 0 ? (
            <details className="border-t border-[hsl(var(--memory-border)/0.45)] pt-4">
              <summary className="cursor-pointer text-sm font-semibold">
                {t('memory.episodes.draft.possible')} ({draft.possible_evidence.length})
              </summary>
              <div className="mt-3 space-y-2">
                {draft.possible_evidence.map((evidence) => {
                  const timeRange = formatEpisodeTimeRange(evidence.time_start, evidence.time_end, i18n.language);
                  return (
                    <label key={`${evidence.ref_type}:${evidence.ref_id}`} className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
                      <input
                        type="checkbox"
                        checked={false}
                        aria-label={evidence.title}
                        onChange={(event) => {
                          if (event.target.checked) addPossibleEvidence(evidence);
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
