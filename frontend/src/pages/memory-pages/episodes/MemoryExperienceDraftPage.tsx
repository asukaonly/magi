import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ChevronDown, ImageIcon, PencilLine, Sparkles } from 'lucide-react';
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
import { ExperienceDraftSegmentCard } from '@/components/memory/experiences/ExperienceDraftSegmentCard';
import ExperienceHero from '@/components/memory/experiences/ExperienceHero';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { formatEpisodeTimeRange } from '@/components/memory/episodes/EpisodeRow';
import { resolveTimelineAssetUrl } from '@/utils/timelineAssetUrl';
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

const formatDraftDateRange = (start: number, end: number, locale: string): string => {
  const formatter = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const startText = formatter.format(new Date(start * 1000));
  const endText = formatter.format(new Date(end * 1000));
  return startText === endText ? startText : `${startText} - ${endText}`;
};

const evidenceRefKey = (refType: string, refId: string) => `${refType}\u0000${refId}`;

const chapterRefKeys = (chapter: ExperienceDraftChapter): string[] => [
  ...chapter.episode_ids.map((refId) => evidenceRefKey('episode', refId)),
  ...chapter.event_ids.map((refId) => evidenceRefKey('event', refId)),
];

const compareChapterOrder = (left: ExperienceDraftChapter, right: ExperienceDraftChapter): number => {
  const orderDifference = Number(left.draft_order) - Number(right.draft_order);
  return orderDifference || left.chapter_id.localeCompare(right.chapter_id);
};

const normalizeChapters = (chapters: ExperienceDraftChapter[]): ExperienceDraftChapter[] => {
  const ordered = chapters
    .map((chapter, index) => (
      Number.isFinite(chapter.draft_order) ? chapter : { ...chapter, draft_order: index }
    ))
    .sort(compareChapterOrder);
  const seen = new Set<string>();
  return ordered.map((chapter) => {
    const hadEvidence = chapter.episode_ids.length > 0 || chapter.event_ids.length > 0;
    const episodeIds = chapter.episode_ids.filter((refId) => {
      const key = evidenceRefKey('episode', refId);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const eventIds = chapter.event_ids.filter((refId) => {
      const key = evidenceRefKey('event', refId);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (hadEvidence && episodeIds.length === 0 && eventIds.length === 0) return null;
    if (episodeIds.length === chapter.episode_ids.length && eventIds.length === chapter.event_ids.length) {
      return chapter;
    }
    const filteredChapter = { ...chapter, episode_ids: episodeIds, event_ids: eventIds };
    delete filteredChapter.event_count;
    return filteredChapter;
  }).filter((chapter): chapter is ExperienceDraftChapter => chapter !== null);
};

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
  const chapters = normalizeChapters(draft.chapters);
  const selectedKeys = new Set(chapters.flatMap(chapterRefKeys));
  const possibleEvidence = dedupeEvidence(draft.possible_evidence, selectedKeys);
  const possibleKeys = new Set(possibleEvidence.map((item) => evidenceRefKey(item.ref_type, item.ref_id)));
  const excludedEvidence = dedupeEvidence(
    draft.excluded_evidence,
    new Set([...selectedKeys, ...possibleKeys]),
  );
  const changed = chapters.length !== draft.chapters.length
    || chapters.some((chapter, index) => chapter !== draft.chapters[index])
    || possibleEvidence.length !== draft.possible_evidence.length
    || possibleEvidence.some((item, index) => item !== draft.possible_evidence[index])
    || excludedEvidence.length !== draft.excluded_evidence.length
    || excludedEvidence.some((item, index) => item !== draft.excluded_evidence[index]);
  return {
    draft: changed ? {
      ...draft,
      chapters,
      possible_evidence: possibleEvidence,
      excluded_evidence: excludedEvidence,
    } : draft,
    changed,
  };
};

const nextChapterOrder = (draft: ExperienceDraft): number => {
  const orders = [
    ...draft.chapters.map((chapter) => chapter.draft_order),
    ...draft.possible_evidence.map((item) => item.restore_chapter?.chapter_order),
  ].filter((value): value is number => Number.isFinite(value));
  return orders.length > 0 ? Math.max(...orders) + 1 : 0;
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

const sameChapterRefs = (
  left: ExperienceDraftChapter,
  right: ExperienceDraftChapter,
): boolean => {
  const leftRefs = new Set(chapterRefKeys(left));
  const rightRefs = new Set(chapterRefKeys(right));
  return leftRefs.size === rightRefs.size
    && [...leftRefs].every((ref) => rightRefs.has(ref));
};

const mergeHydratedChapterCounts = (
  current: ExperienceDraft,
  saved: ExperienceDraft,
  snapshot: ExperienceDraft,
): ExperienceDraft => {
  const savedById = new Map(saved.chapters.map((chapter) => [chapter.chapter_id, chapter]));
  const snapshotById = new Map(snapshot.chapters.map((chapter) => [chapter.chapter_id, chapter]));
  let changed = false;
  const chapters = current.chapters.map((chapter) => {
    const savedChapter = savedById.get(chapter.chapter_id);
    const snapshotChapter = snapshotById.get(chapter.chapter_id);
    if (!savedChapter || !snapshotChapter) return chapter;
    if (typeof snapshotChapter.event_count === 'number') return chapter;
    if (!sameChapterRefs(chapter, snapshotChapter) || !sameChapterRefs(chapter, savedChapter)) {
      return chapter;
    }
    if (typeof savedChapter.event_count !== 'number' || !Number.isFinite(savedChapter.event_count)) {
      return chapter;
    }
    if (chapter.event_count === savedChapter.event_count) return chapter;
    changed = true;
    return { ...chapter, event_count: savedChapter.event_count };
  });
  return changed ? { ...current, chapters } : current;
};

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

interface DraftSaveContext {
  draftId: string;
  draft: ExperienceDraft | null;
  revision: number;
  savedRevision: number;
  queuedRevision: number;
  saveQueue: Promise<void>;
  pendingSaveCount: number;
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
  const [createFailed, setCreateFailed] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [possibleOpen, setPossibleOpen] = useState(false);
  const [editingPreview, setEditingPreview] = useState(false);
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverFailed, setCoverFailed] = useState(false);
  const [localCoverUrl, setLocalCoverUrl] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const saveContextRef = useRef<DraftSaveContext | null>(null);
  const pendingFocusRef = useRef<PendingFocus | null>(null);
  const chapterCheckboxRefs = useRef(new Map<string, HTMLInputElement>());
  const possibleCheckboxRefs = useRef(new Map<string, HTMLInputElement>());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const localCoverUrlRef = useRef<string | null>(null);

  const replaceLocalCoverUrl = useCallback((nextUrl: string | null) => {
    if (localCoverUrlRef.current) URL.revokeObjectURL(localCoverUrlRef.current);
    localCoverUrlRef.current = nextUrl;
    setLocalCoverUrl(nextUrl);
  }, []);

  useEffect(() => () => {
    if (localCoverUrlRef.current) URL.revokeObjectURL(localCoverUrlRef.current);
  }, []);

  useEffect(() => {
    const context: DraftSaveContext = {
      draftId: draftId ?? '',
      draft: null,
      revision: 0,
      savedRevision: 0,
      queuedRevision: 0,
      saveQueue: Promise.resolve(),
      pendingSaveCount: 0,
    };
    saveContextRef.current = context;
    setDraft(null);
    setLoading(true);
    setSaving(false);
    setSaveFailed(false);
    setCreating(false);
    setCreateFailed(false);
    setNotFound(false);
    setPossibleOpen(false);
    setEditingPreview(false);
    setCoverSaving(false);
    setCoverFailed(false);
    replaceLocalCoverUrl(null);
    setAnnouncement('');
    pendingFocusRef.current = null;
    chapterCheckboxRefs.current.clear();
    possibleCheckboxRefs.current.clear();
    if (!draftId) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    let cancelled = false;
    void memoryApi.getExperienceDraft(draftId)
      .then((payload) => {
        if (!cancelled && saveContextRef.current === context) {
          const normalized = normalizeDraftEvidence(payload);
          context.draft = normalized.draft;
          context.revision = normalized.changed ? 1 : 0;
          setDraft(normalized.draft);
        }
      })
      .catch(() => {
        if (!cancelled && saveContextRef.current === context) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled && saveContextRef.current === context) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [draftId, replaceLocalCoverUrl]);

  const enqueueSave = useCallback((
    context: DraftSaveContext,
    snapshot: ExperienceDraft,
    revision: number,
  ): Promise<void> => {
    if (revision <= context.queuedRevision) return context.saveQueue;

    context.queuedRevision = revision;
    context.pendingSaveCount += 1;
    if (saveContextRef.current === context) setSaving(true);
    const priorSave = context.saveQueue.catch(() => undefined);
    const nextSave = priorSave.then(async () => {
      if (saveContextRef.current === context) setSaveFailed(false);
      try {
        const savedDraft = await memoryApi.updateExperienceDraft(
          context.draftId,
          toUpdatePayload(snapshot),
        );
        context.savedRevision = Math.max(context.savedRevision, revision);
        if (saveContextRef.current === context && context.draft) {
          const merged = mergeHydratedChapterCounts(context.draft, savedDraft, snapshot);
          context.draft = merged;
          setDraft((current) => {
            if (saveContextRef.current !== context || current?.draft_id !== context.draftId) {
              return current;
            }
            return mergeHydratedChapterCounts(current, savedDraft, snapshot);
          });
        }
      } catch (error) {
        if (context.queuedRevision === revision) {
          context.queuedRevision = context.savedRevision;
        }
        if (saveContextRef.current === context) setSaveFailed(true);
        throw error;
      } finally {
        context.pendingSaveCount -= 1;
        if (saveContextRef.current === context && context.pendingSaveCount === 0) {
          setSaving(false);
        }
      }
    });
    context.saveQueue = nextSave;
    return nextSave;
  }, []);

  useEffect(() => {
    const context = saveContextRef.current;
    if (!draftId || !draft || !context || context.draftId !== draftId) return;
    const revision = context.revision;
    if (revision <= context.savedRevision || revision <= context.queuedRevision) return;
    const timer = window.setTimeout(() => {
      void enqueueSave(context, draft, revision).catch(() => undefined);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, draftId, enqueueSave]);

  const changeDraft = useCallback((mutate: (current: ExperienceDraft) => ExperienceDraft) => {
    setDraft((current) => {
      const context = saveContextRef.current;
      if (!current || !context || current.draft_id !== context.draftId) return current;
      const normalized = normalizeDraftEvidence(mutate(current)).draft;
      context.revision += 1;
      context.draft = normalized;
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

  const removeChapter = (chapter: ExperienceDraftChapter) => {
    if (typeof chapter.draft_order !== 'number' || !Number.isFinite(chapter.draft_order)) return;
    const restoreChapter = {
      chapter_id: chapter.chapter_id,
      chapter_order: chapter.draft_order,
      episode_ids: chapter.episode_ids,
      event_ids: chapter.event_ids,
      event_count: chapter.event_count,
    };
    const possibleEvidence: ExperienceDraftEvidence[] = [
      ...chapter.episode_ids.map((refId) => ({
        ref_type: 'episode',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
        event_count: chapter.event_count,
        restore_chapter: restoreChapter,
      })),
      ...chapter.event_ids.map((refId) => ({
        ref_type: 'event',
        ref_id: refId,
        title: chapter.title,
        summary: chapter.summary,
        time_start: chapter.time_start,
        time_end: chapter.time_end,
        event_count: chapter.event_count,
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
    const chapterId = restoreChapter?.chapter_id ?? `chapter-${crypto.randomUUID()}`;
    pendingFocusRef.current = {
      section: 'included',
      key: chapterId,
      announcement: `${t('memory.episodes.draft.segments')}: ${evidence.title}`,
    };
    changeDraft((current) => {
      const ownedKeys = new Set(current.chapters.flatMap(chapterRefKeys));
      const availableEvidence = dedupeEvidence(
        current.possible_evidence.filter((item) => (
          restoreChapter
            ? item.restore_chapter?.chapter_id === restoreChapter.chapter_id
            : evidenceRefKey(item.ref_type, item.ref_id) === evidenceRefKey(evidence.ref_type, evidence.ref_id)
        )),
        ownedKeys,
      );
      const episodeIds = availableEvidence
        .filter((item) => item.ref_type === 'episode')
        .map((item) => item.ref_id);
      const eventIds = availableEvidence
        .filter((item) => item.ref_type === 'event')
        .map((item) => item.ref_id);
      const availableKeys = new Set([
        ...episodeIds.map((refId) => evidenceRefKey('episode', refId)),
        ...eventIds.map((refId) => evidenceRefKey('event', refId)),
      ]);
      const restoreKeys = new Set([
        ...(restoreChapter?.episode_ids ?? []).map((refId) => evidenceRefKey('episode', refId)),
        ...(restoreChapter?.event_ids ?? []).map((refId) => evidenceRefKey('event', refId)),
      ]);
      const completeRestore = Boolean(restoreChapter)
        && availableKeys.size === restoreKeys.size
        && [...availableKeys].every((key) => restoreKeys.has(key));
      const restoredEventCount = completeRestore
        ? restoreChapter?.event_count ?? evidence.event_count
        : undefined;
      const chapterWithoutCount: ExperienceDraftChapter = {
        chapter_id: chapterId,
        draft_order: restoreChapter?.chapter_order ?? nextChapterOrder(current),
        title: evidence.title,
        summary: evidence.summary,
        time_start: evidence.time_start,
        time_end: evidence.time_end,
        episode_ids: episodeIds,
        event_ids: eventIds,
      };
      const chapter = restoredEventCount === undefined
        ? chapterWithoutCount
        : { ...chapterWithoutCount, event_count: restoredEventCount };
      return {
        ...current,
        chapters: [...current.chapters.filter((item) => item.chapter_id !== chapter.chapter_id), chapter],
        possible_evidence: current.possible_evidence.filter((item) => (
          restoreChapter
            ? item.restore_chapter?.chapter_id !== restoreChapter.chapter_id
            : evidenceRefKey(item.ref_type, item.ref_id) !== evidenceRefKey(evidence.ref_type, evidence.ref_id)
        )),
      };
    });
  };

  const flushLatestDraft = useCallback(async (context: DraftSaveContext) => {
    while (context.savedRevision < context.revision) {
      const latestDraft = context.draft;
      if (!latestDraft) return;
      await enqueueSave(context, latestDraft, context.revision);
    }
  }, [enqueueSave]);

  const createExperience = async () => {
    const context = saveContextRef.current;
    if (!draftId || !context?.draft || context.draftId !== draftId) return;
    setCreateFailed(false);
    setCreating(true);
    try {
      await flushLatestDraft(context);
      if (saveContextRef.current !== context) return;
      const result = await memoryApi.createExperienceFromDraft(draftId);
      if (saveContextRef.current === context) {
        navigate(`/memory/episodes/${result.experience_id}`);
      }
    } catch {
      if (saveContextRef.current === context) setCreateFailed(true);
    } finally {
      if (saveContextRef.current === context) setCreating(false);
    }
  };

  const updateCover = async (file: File) => {
    const context = saveContextRef.current;
    if (!draftId || !context || context.draftId !== draftId) return;
    const previewUrl = URL.createObjectURL(file);
    replaceLocalCoverUrl(previewUrl);
    setCoverFailed(false);
    setCoverSaving(true);
    try {
      const updatedDraft = await memoryApi.uploadExperienceDraftCover(draftId, file);
      if (saveContextRef.current !== context) return;
      context.draft = context.draft
        ? { ...context.draft, user_cover_asset_ref: updatedDraft.user_cover_asset_ref }
        : context.draft;
      setDraft((current) => (
        current?.draft_id === draftId
          ? { ...current, user_cover_asset_ref: updatedDraft.user_cover_asset_ref }
          : current
      ));
      replaceLocalCoverUrl(null);
    } catch {
      if (saveContextRef.current === context) {
        replaceLocalCoverUrl(null);
        setCoverFailed(true);
      }
    } finally {
      if (saveContextRef.current === context) setCoverSaving(false);
    }
  };

  const visibleDraft = draft?.draft_id === draftId ? draft : null;
  const visibleLoading = loading || (!visibleDraft && !notFound);
  const activeSaving = saveContextRef.current?.draftId === draftId && saving;
  const activeSaveFailed = saveContextRef.current?.draftId === draftId && saveFailed;
  const possibleSegments = visibleDraft ? getPossibleSegments(visibleDraft.possible_evidence) : [];
  const draftDateRange = visibleDraft
    ? formatDraftDateRange(visibleDraft.time_start, visibleDraft.time_end, i18n.language)
    : '';
  const displayCoverUrl = localCoverUrl || resolveTimelineAssetUrl(visibleDraft?.user_cover_asset_ref);

  return (
    <MemoryPageFrame
      title={t('memory.episodes.draft.title')}
      description=""
      hideHeader
      className="max-w-none gap-0 px-0 py-0"
      contentClassName="flex min-h-full flex-col pb-0"
    >
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {[announcement, activeSaving ? t('common.saving') : ''].filter(Boolean).join(' ')}
      </div>

      {visibleLoading ? <div className={`m-6 ${MEMORY_INFO_PANEL_CLASS}`}>{t('common.loading')}</div> : null}
      {!visibleLoading && (notFound || !visibleDraft) ? (
        <div className={`m-6 ${MEMORY_EMPTY_PANEL_CLASS}`}>{t('memory.episodes.draft.notFound')}</div>
      ) : null}
      {visibleDraft ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <main className="w-full flex-1 space-y-8 px-4 pb-8 pt-3 sm:px-8 sm:pb-10">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              aria-label={t('memory.episodes.actions.changeCoverFile')}
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void updateCover(file);
              }}
            />

            <div className="mx-auto w-full max-w-[1180px]">
              <ExperienceHero
                coverUrl={displayCoverUrl}
                title={visibleDraft.title}
                titleLevel={1}
                eyebrow={t('memory.episodes.draft.previewEyebrow')}
                topContent={(
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={t('memory.episodes.draft.back')}
                      className="h-7 shrink-0 px-0 text-xs text-[hsl(var(--memory-muted))] hover:bg-transparent hover:text-[hsl(var(--memory-title))]"
                      onClick={() => navigate('/memory/episodes')}
                    >
                      <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>{t('memory.episodes.draft.back')}</span>
                    </Button>
                    <span className="flex min-w-0 items-start gap-2 leading-5">
                      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
                      <span>{t('memory.episodes.draft.queryContext', { query: visibleDraft.query_text })}</span>
                    </span>
                  </div>
                )}
                actions={(
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={coverSaving}
                      onClick={() => fileInputRef.current?.click()}
                      className="h-9 border-[hsl(var(--memory-border)/0.62)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-3 text-xs shadow-none"
                    >
                      <ImageIcon className="h-3.5 w-3.5" aria-hidden="true" />
                      {coverSaving ? t('common.saving') : t('memory.episodes.actions.changeCover')}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingPreview((current) => !current)}
                      className="h-9 border-[hsl(var(--memory-border)/0.62)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-3 text-xs shadow-none"
                    >
                      <PencilLine className="h-3.5 w-3.5" aria-hidden="true" />
                      {editingPreview ? t('memory.episodes.draft.finishEditing') : t('memory.episodes.draft.adjustPreview')}
                    </Button>
                  </>
                )}
                metadata={(
                  <>
                    <span>{draftDateRange}</span>
                    <span>{t('memory.episodes.draft.segmentCount', { count: visibleDraft.chapters.length })}</span>
                  </>
                )}
                recapLabel={t('memory.episodes.draft.recap')}
                recap={visibleDraft.one_sentence_review}
              />
              {activeSaveFailed ? (
                <p role="alert" className="mt-3 text-sm text-[hsl(var(--destructive))]">
                  {t('memory.episodes.draft.saveFailed')}
                </p>
              ) : null}
              {coverFailed ? (
                <p role="alert" className="mt-3 text-sm text-[hsl(var(--destructive))]">
                  {t('memory.episodes.draft.coverFailed')}
                </p>
              ) : null}
            </div>

            {editingPreview ? (
              <section className="mx-auto w-full max-w-[900px] rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.32)] p-4 sm:p-5">
                <div className="space-y-4">
                      <label className="block space-y-1.5">
                        <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.title')}</span>
                        <Input
                          aria-label={t('memory.episodes.fields.title')}
                          value={visibleDraft.title}
                          onChange={(event) => changeDraft((current) => ({ ...current, title: event.target.value }))}
                          className="h-10"
                        />
                      </label>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="block space-y-1.5">
                          <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.draft.startDate')}</span>
                          <Input
                            type="date"
                            aria-label={t('memory.episodes.draft.startDate')}
                            value={toDateValue(visibleDraft.time_start)}
                            onChange={(event) => changeDraft((current) => ({
                              ...current,
                              time_start: fromDateValue(event.target.value, 'start') ?? current.time_start,
                            }))}
                            className="h-10 w-full"
                          />
                        </label>
                        <label className="block space-y-1.5">
                          <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.draft.endDate')}</span>
                          <Input
                            type="date"
                            aria-label={t('memory.episodes.draft.endDate')}
                            value={toDateValue(visibleDraft.time_end)}
                            onChange={(event) => changeDraft((current) => ({
                              ...current,
                              time_end: fromDateValue(event.target.value, 'end') ?? current.time_end,
                            }))}
                            className="h-10 w-full"
                          />
                        </label>
                      </div>
                      <label className="block space-y-1.5">
                        <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.draft.recap')}</span>
                        <Textarea
                          aria-label={t('memory.episodes.draft.recap')}
                          value={visibleDraft.one_sentence_review}
                          onChange={(event) => changeDraft((current) => ({
                            ...current,
                            one_sentence_review: event.target.value,
                          }))}
                          className="min-h-24 resize-none text-sm leading-6"
                        />
                      </label>
                </div>
              </section>
            ) : null}

            <section aria-labelledby="draft-segments-title" className="mx-auto w-full max-w-[900px]">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 id="draft-segments-title" className="text-base font-semibold text-[hsl(var(--memory-title))]">
                    {t('memory.episodes.draft.segments')}
                  </h2>
                  <p className="mt-1 text-sm text-[hsl(var(--memory-muted))]">
                    {t('memory.episodes.draft.segmentsHint')}
                  </p>
                </div>
                <span className="shrink-0 text-sm font-medium text-[hsl(var(--memory-accent))]">
                  {t('memory.episodes.draft.selectedCount', { count: visibleDraft.chapters.length })}
                </span>
              </div>

              <div className="mt-4 space-y-3">
                {visibleDraft.chapters.map((chapter) => (
                  <ExperienceDraftSegmentCard
                    key={chapter.chapter_id}
                    chapter={chapter}
                    checkboxRef={(node) => {
                      if (node) chapterCheckboxRefs.current.set(chapter.chapter_id, node);
                      else chapterCheckboxRefs.current.delete(chapter.chapter_id);
                    }}
                    onRemove={() => removeChapter(chapter)}
                  />
                ))}
                {visibleDraft.chapters.length === 0 ? (
                  <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.draft.noSegmentsSelected')}</div>
                ) : null}
              </div>
            </section>

            {possibleSegments.length > 0 ? (
              <details
                open={possibleOpen}
                onToggle={(event) => setPossibleOpen(event.currentTarget.open)}
                className="group mx-auto w-full max-w-[900px] border-t border-[hsl(var(--memory-border)/0.48)] pt-4"
              >
                <summary
                  tabIndex={0}
                  className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-[hsl(var(--memory-title))] marker:content-none"
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    setPossibleOpen((open) => !open);
                  }}
                >
                  <span>{t('memory.episodes.draft.possible')} ({possibleSegments.length})</span>
                  <span className="inline-flex items-center gap-1 text-xs font-normal text-[hsl(var(--memory-muted))]">
                    {t('memory.episodes.draft.possibleHint', { count: possibleSegments.length })}
                    <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
                  </span>
                </summary>
                <div className="mt-3 space-y-2">
                  {possibleSegments.map((segment) => {
                    const { evidence } = segment;
                    const timeRange = formatEpisodeTimeRange(evidence.time_start, evidence.time_end, i18n.language);
                    return (
                      <label key={segment.key} className="flex cursor-pointer items-start gap-3 rounded-md border border-[hsl(var(--memory-border)/0.46)] bg-[hsl(var(--memory-panel-subtle)/0.24)] p-4">
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
                          className="mt-0.5 h-[18px] w-[18px] shrink-0 accent-[hsl(var(--memory-accent))]"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium text-[hsl(var(--memory-title))]">{evidence.title}</span>
                          {evidence.summary ? (
                            <span className="mt-1 block text-sm leading-6 text-[hsl(var(--memory-body))]">{evidence.summary}</span>
                          ) : null}
                          {timeRange ? (
                            <span className="mt-2 block text-xs text-[hsl(var(--memory-muted))]">{timeRange}</span>
                          ) : null}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </details>
            ) : null}
          </main>

          <div className="sticky bottom-0 z-20 border-t border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.97)] px-4 py-4 sm:px-8">
            <div className="mx-auto w-full max-w-[900px]">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-[hsl(var(--memory-body))]">
                  {t('memory.episodes.draft.createSummary', { count: visibleDraft.chapters.length })}
                </p>
                <Button
                  onClick={() => { void createExperience(); }}
                  disabled={creating || !visibleDraft.title.trim() || visibleDraft.chapters.length === 0}
                  className="h-10 px-5 sm:self-auto"
                >
                  {creating ? t('common.saving') : t('memory.episodes.draft.create')}
                </Button>
              </div>
              {createFailed ? (
                <p role="alert" className="mt-2 text-sm text-[hsl(var(--destructive))]">
                  {t('memory.episodes.draft.createFailed')}
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </MemoryPageFrame>
  );
};
