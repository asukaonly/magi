import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Feather, Image as ImageIcon, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { timelineApi, type TimelineClusterBlock, type TimelineContextBundle, type TimelineViewportResponse } from "@/api/modules/timeline";
import { type ManualEntry, type MoodValence, weatherEmoji } from "@/api/modules/manualEntries";
import { ProtectedImage } from "@/components/media/ProtectedImage";
import { renderRichTextHtml } from "@/components/timeline/manual-entries/renderRichText";
import { cn } from "@/lib/utils";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";
import { SourceIcon, labelForSource } from "./SourceIcon";
import { EvidenceReader } from "./EvidenceReader";
import { formatClock, readableText, sceneBody, sceneTitle } from "./scene-presentation";
import './day-scene-reader.css';

interface DaySceneReaderProps {
  viewport: TimelineViewportResponse;
  dateLabel: string;
  placeLine?: string;
  coverUrl?: string | null;
  manualEntries: ManualEntry[];
  onOpenExperience?: (experienceId: string) => void;
  onOrganizeExperience?: () => void;
  onAddNote?: () => void;
  onEditManualEntry?: (entry: ManualEntry) => void;
  onDeleteManualEntry?: (entryId: string) => void;
  onOpenCover?: () => void;
}

const MOOD_EMOJI: Record<MoodValence, string> = { warm: "😌", bright: "😊", neutral: "😐", cool: "😔", tense: "😣" };

export const DaySceneReader: React.FC<DaySceneReaderProps> = ({
  viewport, dateLabel, placeLine, coverUrl, manualEntries, onOpenExperience,
  onOrganizeExperience, onAddNote, onEditManualEntry, onDeleteManualEntry, onOpenCover,
}) => {
  const { t } = useTranslation("app");
  const orderedClusters = useMemo(() => [...(viewport.clusters ?? [])]
    .filter(cluster => cluster.source_types?.[0] !== "manual_entry")
    .sort((a, b) => a.time_start - b.time_start), [viewport.clusters]);
  const [selectedCluster, setSelectedCluster] = useState<TimelineClusterBlock | null>(null);
  const [context, setContext] = useState<TimelineContextBundle | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState(false);
  const requestIdRef = useRef(0);
  const contextTriggerRef = useRef<HTMLButtonElement | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollSnapshot = useRef<{ element: HTMLElement; top: number } | null>(null);
  const summary = readableText(viewport.overview?.essence_prose) || readableText(viewport.overview?.summary);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const hasScenes = orderedClusters.length > 0;

  const closeContext = useCallback((restoreFocus = true) => {
    requestIdRef.current += 1;
    setSelectedCluster(null); setContext(null); setContextLoading(false); setContextError(false);
    if (restoreFocus) {
      requestAnimationFrame(() => {
        const snapshot = scrollSnapshot.current;
        if (snapshot) snapshot.element.scrollTop = snapshot.top;
        contextTriggerRef.current?.focus({ preventScroll: true });
      });
    }
  }, []);
  useEffect(() => {
    closeContext(false);
    setSummaryExpanded(false);
    return () => { requestIdRef.current += 1; };
  }, [closeContext, viewport.viewport.start, viewport.viewport.end, viewport.viewport.query, viewport.viewport.locale]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape" && selectedCluster) closeContext(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeContext, selectedCluster]);

  const loadContext = useCallback(async (cluster: TimelineClusterBlock) => {
    const requestId = ++requestIdRef.current;
    setContext(null); setContextError(false); setContextLoading(true);
    try {
      const bundle = cluster.episode_id
        ? await timelineApi.getContext(`episode:${cluster.episode_id}`)
        : cluster.source_event_ids?.length
          ? await timelineApi.getEventContext(cluster.source_event_ids)
          : null;
      if (requestIdRef.current === requestId) setContext(bundle);
    } catch {
      if (requestIdRef.current === requestId) setContextError(true);
    } finally {
      if (requestIdRef.current === requestId) setContextLoading(false);
    }
  }, []);
  const openContext = (cluster: TimelineClusterBlock, trigger: HTMLButtonElement) => {
    contextTriggerRef.current = trigger;
    const scrollParent = rootRef.current?.closest<HTMLElement>('.overflow-y-auto');
    if (!selectedCluster && scrollParent) scrollSnapshot.current = { element: scrollParent, top: scrollParent.scrollTop };
    setSelectedCluster(cluster);
    if (scrollParent) scrollParent.scrollTop = 0;
    void loadContext(cluster);
  };

  return <div ref={rootRef} className="timeline-reader min-h-full bg-background text-foreground" data-detail-open={Boolean(selectedCluster)}>
    <div className="mx-auto w-full max-w-[1400px] px-5 py-7 sm:px-8 lg:px-10">
      <header className="timeline-day-summary mb-6">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-[25px] font-semibold leading-9 tracking-tight">{dateLabel}</h1>
          <div className="flex shrink-0 items-center gap-2">
            {onAddNote ? <button type="button" onClick={onAddNote} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"><Feather className="h-4 w-4" aria-hidden="true" />{t('timeline.review.addNote')}</button> : null}
            {onOpenCover ? <button type="button" onClick={onOpenCover} aria-label={t('timeline.cover.open')} className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-md text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
              {coverUrl ? <ProtectedImage data-testid="timeline-day-cover" src={coverUrl} alt="" className="h-full w-full object-cover" /> : <ImageIcon className="h-4 w-4" />}
            </button> : null}
          </div>
        </div>
        {summary ? <div className="mt-3 max-w-[860px]"><p className={cn('text-[15px] leading-7 text-foreground/80', !summaryExpanded && 'line-clamp-2')}>{summary}</p>
          {summary.length > 95 ? <button type="button" onClick={() => setSummaryExpanded(value => !value)} aria-expanded={summaryExpanded} className="mt-1 text-[12px] text-muted-foreground hover:text-foreground">{t(summaryExpanded ? 'timeline.review.less' : 'timeline.review.more')}</button> : null}
        </div> : !hasScenes && manualEntries.filter(entry => !entry.deleted_at).length === 0 ? <p className="mt-3 text-[14px] text-muted-foreground">{t('timeline.immersive.scene.emptyDayBody')}</p> : null}
        <p className="mt-3 text-[12px] text-muted-foreground">{t('timeline.review.records', { count: viewport.summary?.event_count || 0 })}{placeLine ? ` · ${placeLine}` : ''}</p>
      </header>
      <div className="timeline-reader-layout">
        <div className="timeline-records min-w-0">
          <div className="divide-y divide-border/55 border-t border-border/55">
            {orderedClusters.map(cluster => <SceneRow key={cluster.block_id || cluster.episode_id || cluster.time_start} cluster={cluster}
              selected={selectedCluster?.block_id === cluster.block_id && selectedCluster !== null}
              onOpen={trigger => openContext(cluster, trigger)} />)}
          </div>
          <ManualNotes entries={manualEntries} hasScenes={hasScenes} onAdd={hasScenes ? undefined : onAddNote} onEdit={onEditManualEntry} onDelete={onDeleteManualEntry} />
        </div>
        {selectedCluster ? <EvidenceReader key={selectedCluster.block_id || selectedCluster.episode_id} cluster={selectedCluster} context={context} loading={contextLoading} failed={contextError}
          onClose={() => closeContext()} onRetry={() => void loadContext(selectedCluster)} onOpenExperience={onOpenExperience} onOrganizeExperience={onOrganizeExperience} /> : null}
      </div>
    </div>
  </div>;
};

function SceneRow({ cluster, selected, onOpen }: { cluster: TimelineClusterBlock; selected: boolean; onOpen: (trigger: HTMLButtonElement) => void }) {
  const { t } = useTranslation('app');
  const source = cluster.source_types?.[0] || 'memory';
  const title = sceneTitle(cluster, labelForSource(source, t));
  const body = sceneBody(cluster, title);
  const imageUrl = resolveTimelineAssetUrl(cluster.representative_asset_ref || null);
  return <button type="button" onClick={event => onOpen(event.currentTarget)} aria-expanded={selected}
    aria-controls={selected ? 'timeline-evidence-reader' : undefined} aria-label={t('timeline.review.openRecord', { title })}
    className={cn('grid w-full grid-cols-[42px_28px_minmax(0,1fr)_14px] items-start gap-3 rounded-md px-2 py-4 text-left transition-colors hover:bg-muted/45 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[52px_28px_minmax(0,1fr)_14px]', selected && 'bg-primary/6 ring-1 ring-inset ring-primary/20')}>
    <time className="mt-0.5 text-[12px] tabular-nums text-muted-foreground">{formatClock(cluster.time_start)}</time>
    <span className="mt-0.5 flex h-7 w-7 items-center justify-center"><SourceIcon sourceType={source} className="h-6 w-6 shrink-0" /></span>
    <span className="min-w-0">
      <span className="line-clamp-2 block text-[16px] font-medium leading-6 wrap-anywhere">{title}</span>
      {body ? <span className="timeline-row-summary mt-1.5 line-clamp-2 text-[14px] leading-6 text-muted-foreground wrap-anywhere">{body}</span> : null}
      <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground">
        <span>{labelForSource(source, t)}</span><span>·</span><span>{t('timeline.review.records', { count: cluster.event_count || 0 })}</span>
        {cluster.experience_id ? <span className="text-primary/85">· {cluster.experience_title || t('timeline.immersive.scene.relation.untitledExperience')}{cluster.experience_chapter_id ? ` · ${t('timeline.immersive.scene.kind.chapter')}` : ''}</span> : null}
      </span>
      {imageUrl ? <ProtectedImage src={imageUrl} alt="" className="mt-3 h-20 w-28 rounded-md object-cover" /> : null}
    </span>
    <ChevronRight className="mt-1 h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
  </button>;
}

const ManualNotes: React.FC<{
  entries: ManualEntry[];
  hasScenes: boolean;
  onAdd?: () => void;
  onEdit?: (entry: ManualEntry) => void;
  onDelete?: (entryId: string) => void;
}> = ({ entries, hasScenes, onAdd, onEdit, onDelete }) => {
  const { t } = useTranslation("app");
  const visibleEntries = entries
    .filter((entry) => !entry.deleted_at)
    .sort((a, b) => a.event_at - b.event_at);
  if (visibleEntries.length === 0 && hasScenes) return null;

  return (
    <section className="mt-8 border-t border-border/55 pt-5">
      {visibleEntries.length > 0 ? (
        <>
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-[13px] font-medium text-muted-foreground">
              {t("timeline.immersive.scene.notes.title", { defaultValue: "只有你记得" })}
            </h2>
            {onAdd ? (
              <button
                type="button"
                onClick={onAdd}
                className="rounded-mem-sm text-[13px] font-medium text-primary outline-hidden transition-colors hover:text-primary/75 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background"
              >
                {t("timeline.immersive.scene.notes.addAnother", { defaultValue: "再补一句" })}
              </button>
            ) : null}
          </div>
          <div className="mt-5 space-y-3">
            {visibleEntries.map((entry) => (
              <ManualNoteRow
                key={entry.entry_id}
                entry={entry}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <p className="text-[13px] text-muted-foreground">
            {t(
              hasScenes
                ? "timeline.immersive.scene.notes.empty"
                : "timeline.immersive.scene.notes.emptyDay",
              {
                defaultValue: hasScenes
                  ? "它还只是当天的记录，不会因为补充一句话就自动变成经历。"
                  : "不用补全这一天，只记你真正想留下的。",
              },
            )}
          </p>
          {onAdd ? (
            <button
              type="button"
              onClick={onAdd}
              className="inline-flex items-center gap-2 rounded-mem-sm text-[13px] font-medium text-primary outline-hidden transition-colors hover:text-primary/75 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background sm:ml-auto"
            >
              <Feather className="h-3.5 w-3.5" />
              {t("timeline.immersive.scene.notes.add", {
                defaultValue: "补一句只有你记得的事",
              })}
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
};

const ManualNoteRow: React.FC<{
  entry: ManualEntry;
  onEdit?: (entry: ManualEntry) => void;
  onDelete?: (entryId: string) => void;
}> = ({ entry, onEdit, onDelete }) => {
  const { t } = useTranslation("app");
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const weather = entry.weather ? weatherEmoji(entry.weather.code) : null;

  useEffect(() => {
    if (previewIndex === null) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewIndex(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewIndex]);

  return (
    <article className="group rounded-mem-md bg-muted/46 px-5 py-4 wrap-anywhere">
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
        <Feather className="h-3.5 w-3.5 text-primary" />
        <span className="tabular-nums">{formatClock(entry.event_at)}</span>
        {entry.mood ? (
          <span
            className="text-[13px] leading-none"
            title={t(`timeline.manualEntry.moods.${entry.mood}`, {
              defaultValue: entry.mood,
            })}
          >
            {MOOD_EMOJI[entry.mood]}
          </span>
        ) : null}
        {weather && entry.weather ? (
          <span
            className="inline-flex items-center gap-0.5 tabular-nums"
            aria-label={`${Math.round(entry.weather.temp_c)}°C`}
          >
            <span aria-hidden="true">{weather}</span>
            {Math.round(entry.weather.temp_c)}°
          </span>
        ) : null}
        {entry.location_label ? <span className="truncate">· {entry.location_label}</span> : null}
        <div className="ml-auto flex items-center gap-1 opacity-100 transition-opacity duration-200 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
          {onEdit ? (
            <button
              type="button"
              onClick={() => onEdit(entry)}
              className="flex h-7 w-7 items-center justify-center rounded-mem-sm outline-hidden transition-colors hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("timeline.manualEntry.editAction", { defaultValue: "编辑" })}
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {onDelete ? (
            <button
              type="button"
              onClick={() => {
                if (
                  window.confirm(
                    t("timeline.manualEntry.confirmDelete", {
                      defaultValue: "删除这条记录？",
                    }),
                  )
                ) {
                  onDelete(entry.entry_id);
                }
              }}
              className="flex h-7 w-7 items-center justify-center rounded-mem-sm outline-hidden transition-colors hover:bg-background hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("timeline.manualEntry.deleteAction", { defaultValue: "删除" })}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>
      {entry.body_doc ? (
        <div
          className="rich-text-content mt-3 text-[14px] leading-7 text-foreground/78"
          dangerouslySetInnerHTML={{
            __html: renderRichTextHtml(entry.body_doc, entry.body),
          }}
        />
      ) : (
        <p className="mt-3 whitespace-pre-wrap text-[14px] leading-7 text-foreground/78">
          {entry.body}
        </p>
      )}
      {entry.attachments.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {entry.attachments.slice(0, 4).map((assetRef, index) => {
            const assetUrl = resolveTimelineAssetUrl(assetRef);
            return assetUrl ? (
              <button
                key={assetRef}
                type="button"
                onClick={() => setPreviewIndex(index)}
                className="h-16 w-20 overflow-hidden rounded-mem-sm outline-hidden transition-opacity hover:opacity-85 focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={t("timeline.manualEntry.openImage", { defaultValue: "查看图片" })}
              >
                <ProtectedImage
                  src={assetUrl}
                  alt=""
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              </button>
            ) : null;
          })}
          {entry.attachments.length > 4 ? (
            <span className="flex h-16 items-end px-1 pb-1 text-[11px] text-muted-foreground">
              +{entry.attachments.length - 4}
            </span>
          ) : null}
        </div>
      ) : null}
      {previewIndex !== null ? (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-foreground/82 p-6"
          role="dialog"
          aria-modal="true"
          aria-label={t("timeline.manualEntry.attachmentAlt", { defaultValue: "附件图片" })}
          onClick={() => setPreviewIndex(null)}
        >
          <ProtectedImage
            src={resolveTimelineAssetUrl(entry.attachments[previewIndex]) ?? ""}
            alt={t("timeline.manualEntry.attachmentAlt", { defaultValue: "附件图片" })}
            eager
            className="max-h-[90vh] max-w-[90vw] rounded-mem-sm object-contain"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      ) : null}
    </article>
  );
};
