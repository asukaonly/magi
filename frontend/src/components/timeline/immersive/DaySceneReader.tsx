import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  Feather,
  Image as ImageIcon,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  timelineApi,
  type TimelineClusterBlock,
  type TimelineContextBundle,
  type TimelineViewportResponse,
} from "@/api/modules/timeline";
import {
  type ManualEntry,
  type MoodValence,
  weatherEmoji,
} from "@/api/modules/manualEntries";
import { ProtectedImage } from "@/components/media/ProtectedImage";
import { renderRichTextHtml } from "@/components/timeline/manual-entries/renderRichText";
import { cn } from "@/lib/utils";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

import { SourceIcon, labelForSource } from "./SourceIcon";

type SceneRelation = "chapter" | "experience" | "independent";

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

const PLACEHOLDER_LABELS = new Set(["", "activity", "event", "memory"]);
const MOOD_EMOJI: Record<MoodValence, string> = {
  warm: "😌",
  bright: "😊",
  neutral: "😐",
  cool: "😔",
  tense: "😣",
};

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function usefulText(value: unknown): string {
  const text = cleanText(value);
  return PLACEHOLDER_LABELS.has(text.toLowerCase()) ? "" : text;
}

function toHeadline(value: string, maxLength = 46): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  const sentenceEnd = text.slice(0, maxLength + 1).search(/[。！？!?]/);
  if (sentenceEnd >= 12) return text.slice(0, sentenceEnd + 1);
  return `${text.slice(0, maxLength).trimEnd()}…`;
}

function relationFor(cluster: TimelineClusterBlock | null): SceneRelation {
  if (cleanText(cluster?.experience_chapter_id)) return "chapter";
  if (cleanText(cluster?.experience_id)) return "experience";
  return "independent";
}

function formatClock(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDuration(seconds: number, t: (key: string, options?: Record<string, unknown>) => string): string {
  const safeSeconds = Math.max(0, seconds);
  if (safeSeconds < 1) {
    return t("timeline.immersive.scene.instant", { defaultValue: "一个瞬间" });
  }
  if (safeSeconds < 90) {
    return t("timeline.immersive.scene.aboutMinute", { defaultValue: "约 1 分钟" });
  }
  if (safeSeconds < 3600) {
    return t("timeline.immersive.scene.minutes", {
      defaultValue: "约 {{count}} 分钟",
      count: Math.max(1, Math.round(safeSeconds / 60)),
    });
  }
  return t("timeline.immersive.scene.hours", {
    defaultValue: "约 {{count}} 小时",
    count: Number((safeSeconds / 3600).toFixed(1)),
  });
}

function sceneAnchor(cluster: TimelineClusterBlock): string | null {
  if (cleanText(cluster.episode_id)) return `episode:${cluster.episode_id}`;
  const eventId = cluster.representative_event_ids?.find((item) => cleanText(item));
  return eventId || null;
}

function sourceLabel(
  cluster: TimelineClusterBlock,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const source = cluster.source_types?.[0] || "memory";
  return labelForSource(source, t);
}

function sceneTitle(cluster: TimelineClusterBlock, fallback: string): string {
  return toHeadline(
    usefulText(cluster.user_label) ||
      usefulText(cluster.label) ||
      usefulText(cluster.slice_narrative) ||
      usefulText(cluster.summary) ||
      fallback,
  );
}

function sceneBody(cluster: TimelineClusterBlock, title: string): string {
  const candidates = [
    usefulText(cluster.slice_narrative),
    usefulText(cluster.summary),
    usefulText(cluster.user_note),
  ];
  return candidates.find((candidate) => candidate && toHeadline(candidate) !== title) || "";
}

function relationRank(cluster: TimelineClusterBlock): number {
  if (cluster.experience_chapter_id) return 3;
  if (cluster.experience_id) return 2;
  return 1;
}

function sortClusters(clusters: TimelineClusterBlock[]): TimelineClusterBlock[] {
  return [...clusters].sort((a, b) => a.time_start - b.time_start);
}

function primaryCluster(clusters: TimelineClusterBlock[]): TimelineClusterBlock | null {
  if (clusters.length === 0) return null;
  return [...clusters].sort((a, b) => {
    if (Boolean(a.user_pinned) !== Boolean(b.user_pinned)) return a.user_pinned ? -1 : 1;
    const relationDifference = relationRank(b) - relationRank(a);
    if (relationDifference !== 0) return relationDifference;
    const countDifference = Number(b.event_count || 0) - Number(a.event_count || 0);
    if (countDifference !== 0) return countDifference;
    return Number(b.duration_seconds || b.time_end - b.time_start) -
      Number(a.duration_seconds || a.time_end - a.time_start);
  })[0];
}

function timeOfDayLabel(
  timestamp: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const hour = new Date(timestamp * 1000).getHours();
  if (hour < 6) {
    return t("timeline.immersive.scene.timeOfDay.lateNight", { defaultValue: "深夜" });
  }
  if (hour < 12) {
    return t("timeline.immersive.scene.timeOfDay.morning", { defaultValue: "上午" });
  }
  if (hour < 18) {
    return t("timeline.immersive.scene.timeOfDay.afternoon", { defaultValue: "下午" });
  }
  return t("timeline.immersive.scene.timeOfDay.evening", { defaultValue: "晚间" });
}

function relationCopy(
  relation: SceneRelation,
  cluster: TimelineClusterBlock | null,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  if (relation === "chapter") {
    return {
      label: t("timeline.immersive.scene.relation.chapterLabel", {
        defaultValue: "所属经历",
      }),
      title:
        cleanText(cluster?.experience_title) ||
        t("timeline.immersive.scene.relation.untitledExperience", {
          defaultValue: "一段经历",
        }),
      body: t("timeline.immersive.scene.relation.chapterBody", {
        defaultValue: "当前场景是这段经历中的一个章节，保留独立的时间和依据。",
      }),
      action: t("timeline.immersive.scene.relation.openExperience", {
        defaultValue: "查看完整经历",
      }),
    };
  }
  if (relation === "experience") {
    return {
      label: t("timeline.immersive.scene.relation.fragmentLabel", {
        defaultValue: "经历片段",
      }),
      title:
        cleanText(cluster?.experience_title) ||
        t("timeline.immersive.scene.relation.untitledExperience", {
          defaultValue: "一段经历",
        }),
      body: t("timeline.immersive.scene.relation.fragmentBody", {
        defaultValue: "它已经属于一段经历，但还没有形成正式章节。",
      }),
      action: t("timeline.immersive.scene.relation.openExperience", {
        defaultValue: "查看完整经历",
      }),
    };
  }
  return {
    label: t("timeline.immersive.scene.relation.independentLabel", {
      defaultValue: "当前状态",
    }),
    title: t("timeline.immersive.scene.relation.independentTitle", {
      defaultValue: "尚未形成经历",
    }),
    body: t("timeline.immersive.scene.relation.independentBody", {
      defaultValue: "先按独立片段保留；只有在值得长期回看时再整理。",
    }),
    action: t("timeline.immersive.scene.relation.organize", {
      defaultValue: "整理为经历",
    }),
  };
}

export const DaySceneReader: React.FC<DaySceneReaderProps> = ({
  viewport,
  dateLabel,
  placeLine,
  coverUrl,
  manualEntries,
  onOpenExperience,
  onOrganizeExperience,
  onAddNote,
  onEditManualEntry,
  onDeleteManualEntry,
  onOpenCover,
}) => {
  const { t } = useTranslation("app");
  const orderedClusters = useMemo(
    () =>
      sortClusters(
        (viewport.clusters ?? []).filter(
          (cluster) => cluster.source_types?.[0] !== "manual_entry",
        ),
      ),
    [viewport.clusters],
  );
  const hasScenes = orderedClusters.length > 0;
  const visibleManualEntries = useMemo(
    () => manualEntries.filter((entry) => !entry.deleted_at),
    [manualEntries],
  );
  const hasManualNotes = visibleManualEntries.length > 0;
  const hasDayContent = hasScenes || hasManualNotes;
  const primary = useMemo(() => primaryCluster(orderedClusters), [orderedClusters]);
  const relation = relationFor(primary);
  const relationContent = relationCopy(relation, primary, t);
  const requestIdRef = useRef(0);
  const contextTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<TimelineClusterBlock | null>(null);
  const [context, setContext] = useState<TimelineContextBundle | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState(false);

  const fallbackTitle = t("timeline.immersive.scene.untitledScene", {
    defaultValue: "一个被留下的片段",
  });
  const manualFallback = visibleManualEntries[0]?.body || "";
  const title = toHeadline(
    usefulText(primary?.user_label) ||
      usefulText(viewport.overview?.title) ||
      usefulText(primary?.experience_chapter_title) ||
      usefulText(primary?.label) ||
      usefulText(primary?.slice_narrative) ||
      usefulText(primary?.summary) ||
      usefulText(manualFallback) ||
      t(
        hasDayContent
          ? "timeline.immersive.scene.dayFallbackTitle"
          : "timeline.immersive.scene.emptyDayTitle",
        {
          defaultValue: hasDayContent ? "这一天留下了一些片段" : "这一天还没有留下记录",
        },
      ),
    52,
  );
  const body =
    usefulText(viewport.overview?.essence_prose) ||
    usefulText(viewport.overview?.summary) ||
    sceneBody(primary ?? ({} as TimelineClusterBlock), title) ||
    (!hasScenes && hasManualNotes
      ? t("timeline.immersive.scene.manualOnlyBody", {
          defaultValue: "这是你亲自留给这一天的一句话，不需要再被补写成完整故事。",
        })
      : t(
          hasScenes
            ? "timeline.immersive.scene.dayFallbackBody"
            : "timeline.immersive.scene.emptyDayBody",
          {
            defaultValue: hasScenes
              ? "这里保留当天能确认的场景，不急着把零散记录写成结论。"
              : "想起什么时，可以先留下一句话。它会留在当天，不会被急着写成结论。",
          },
        ));
  const totalEvidence = Math.max(
    Number(viewport.summary?.event_count || 0),
    orderedClusters.reduce((sum, cluster) => sum + Number(cluster.event_count || 0), 0),
  );
  const eyebrow = t(
    !hasScenes
      ? hasManualNotes
        ? "timeline.immersive.scene.eyebrow.manual"
        : "timeline.immersive.scene.eyebrow.empty"
      : relation === "chapter"
        ? "timeline.immersive.scene.eyebrow.chapter"
        : relation === "experience"
          ? "timeline.immersive.scene.eyebrow.experience"
          : "timeline.immersive.scene.eyebrow.independent",
    {
      defaultValue:
        !hasScenes
          ? hasManualNotes
            ? "只有你记得"
            : "一天的留白"
          : relation === "chapter"
          ? "经历中的一天"
          : relation === "experience"
            ? "经历中的片段"
            : "一天中的片段",
    },
  );

  const closeContext = useCallback((restoreFocus = true) => {
    requestIdRef.current += 1;
    setSelectedCluster(null);
    setContext(null);
    setContextLoading(false);
    setContextError(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => contextTriggerRef.current?.focus());
    } else {
      contextTriggerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && selectedCluster) closeContext(true);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeContext, selectedCluster]);

  useEffect(() => {
    closeContext(false);
  }, [closeContext, viewport.viewport.end, viewport.viewport.start]);

  const openContext = useCallback(async (
    cluster: TimelineClusterBlock,
    trigger: HTMLButtonElement,
  ) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    contextTriggerRef.current = trigger;
    setSelectedCluster(cluster);
    setContext(null);
    setContextError(false);
    const anchor = sceneAnchor(cluster);
    if (!anchor) {
      setContextLoading(false);
      return;
    }
    setContextLoading(true);
    try {
      const bundle = await timelineApi.getContext(anchor);
      if (requestIdRef.current !== requestId) return;
      setContext(bundle);
    } catch {
      if (requestIdRef.current !== requestId) return;
      setContextError(true);
    } finally {
      if (requestIdRef.current === requestId) setContextLoading(false);
    }
  }, []);

  const handleRelationAction = () => {
    if (primary?.experience_id && onOpenExperience) {
      onOpenExperience(primary.experience_id);
      return;
    }
    onOrganizeExperience?.();
  };

  return (
    <div className="min-h-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1220px] px-5 pb-20 pt-14 sm:px-10 lg:px-14 lg:pt-20">
        <header className="relative max-w-[980px]">
          <div className="flex items-center justify-between gap-5">
            <p className="text-[12px] font-semibold tracking-[0.12em] text-primary">
              {eyebrow}
              {primary ? ` · ${timeOfDayLabel(primary.time_start, t)}` : ""}
            </p>
            {onOpenCover ? (
              <button
                type="button"
                onClick={onOpenCover}
                className={cn(
                  "group flex items-center justify-center overflow-hidden text-muted-foreground outline-none transition-colors duration-200",
                  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background",
                  coverUrl
                    ? "h-20 w-28 rounded-mem-md bg-muted sm:h-24 sm:w-36"
                    : "h-9 w-9 rounded-mem-sm hover:bg-muted hover:text-foreground",
                )}
                aria-label={t("timeline.cover.open", { defaultValue: "更换封面" })}
                title={t("timeline.cover.open", { defaultValue: "更换封面" })}
              >
                {coverUrl ? (
                  <ProtectedImage
                    data-testid="timeline-day-cover"
                    src={coverUrl}
                    alt=""
                    eager
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                  />
                ) : (
                  <ImageIcon className="h-4 w-4" />
                )}
              </button>
            ) : null}
          </div>

          <h1 className="mt-7 max-w-[940px] text-[clamp(2.35rem,4vw,4rem)] font-semibold leading-[1.1] tracking-[-0.04em] text-foreground">
            {title}
          </h1>
          <p className="mt-7 max-w-[900px] text-[18px] leading-[1.8] text-foreground/68 sm:text-[21px]">
            {body}
          </p>
          <p className="mt-7 text-[13px] tracking-[0.02em] text-muted-foreground">
            {dateLabel}
            {placeLine ? ` · ${placeLine}` : ""}
            {primary ? ` · ${formatClock(primary.time_start)}–${formatClock(primary.time_end)}` : ""}
            {totalEvidence > 0
              ? ` · ${t("timeline.immersive.scene.evidenceCount", {
                  defaultValue: "{{count}} 条依据",
                  count: totalEvidence,
                })}`
              : ""}
          </p>
        </header>

        {hasScenes ? (
          <section
            className="mt-12 grid gap-6 rounded-mem-lg bg-primary/[0.065] px-6 py-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-8"
            aria-label={t("timeline.immersive.scene.relation.label", {
              defaultValue: "与经历的关系",
            })}
          >
            <div className="grid gap-1.5 sm:grid-cols-[150px_minmax(0,1fr)] sm:gap-7">
              <p className="text-[12px] font-semibold text-primary">{relationContent.label}</p>
              <div>
                <h2 className="text-[17px] font-semibold tracking-[-0.01em]">
                  {relationContent.title}
                </h2>
                <p className="mt-1.5 text-[14px] leading-6 text-muted-foreground">
                  {relationContent.body}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleRelationAction}
              className={cn(
                "inline-flex h-10 items-center justify-center gap-2 rounded-mem-sm px-4 text-[13px] font-medium outline-none transition-colors duration-200",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background",
                relation === "independent"
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "text-primary hover:bg-primary/10",
              )}
            >
              {relationContent.action}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </section>
        ) : null}

        <div className={cn("flex items-start", hasScenes ? "mt-14" : "mt-4")}>
          <div className="min-w-0 flex-1">
            {hasScenes ? (
              <>
                <div className="flex items-center gap-5">
                  <h2 className="shrink-0 text-[13px] font-medium text-muted-foreground">
                    {relation === "chapter"
                      ? t("timeline.immersive.scene.section.chapter", {
                          defaultValue: "这一章",
                        })
                      : t("timeline.immersive.scene.section.day", { defaultValue: "当天" })}
                  </h2>
                  <div className="h-px flex-1 bg-border/55" />
                </div>

                <div className="mt-9 space-y-12">
                  {orderedClusters.map((cluster, index) => (
                    <SceneRow
                      key={cluster.block_id || cluster.episode_id || `${cluster.time_start}`}
                      cluster={cluster}
                      fallbackTitle={fallbackTitle}
                      selected={selectedCluster === cluster}
                      last={index === orderedClusters.length - 1}
                      onOpen={(trigger) => void openContext(cluster, trigger)}
                    />
                  ))}
                </div>
              </>
            ) : null}

            <ManualNotes
              entries={manualEntries}
              hasScenes={hasScenes}
              onAdd={onAddNote}
              onEdit={onEditManualEntry}
              onDelete={onDeleteManualEntry}
            />
          </div>

          <AnimatePresence initial={false}>
            {selectedCluster ? (
              <EvidenceDrawer
                key={selectedCluster.block_id || selectedCluster.episode_id}
                cluster={selectedCluster}
                context={context}
                loading={contextLoading}
                failed={contextError}
                onClose={closeContext}
              />
            ) : null}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
};

const SceneRow: React.FC<{
  cluster: TimelineClusterBlock;
  fallbackTitle: string;
  selected: boolean;
  last: boolean;
  onOpen: (trigger: HTMLButtonElement) => void;
}> = ({ cluster, fallbackTitle, selected, last, onOpen }) => {
  const { t } = useTranslation("app");
  const relation = relationFor(cluster);
  const title = sceneTitle(cluster, fallbackTitle);
  const body = sceneBody(cluster, title);
  const source = cluster.source_types?.[0] || "memory";
  const imageUrl = resolveTimelineAssetUrl(cluster.representative_asset_ref || null);
  const relationLabel = t(`timeline.immersive.scene.kind.${relation}`, {
    defaultValue:
      relation === "chapter"
        ? "经历章节"
        : relation === "experience"
          ? "经历片段"
          : "独立片段",
  });

  return (
    <article className="grid grid-cols-[52px_14px_minmax(0,1fr)] gap-2 sm:grid-cols-[92px_22px_minmax(0,1fr)] sm:gap-4">
      <div className="pt-0.5 text-right">
        <p className="text-[15px] font-semibold tabular-nums">{formatClock(cluster.time_start)}</p>
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
          {formatDuration(cluster.duration_seconds || cluster.time_end - cluster.time_start, t)}
        </p>
      </div>

      <div className="relative flex justify-center">
        {!last ? (
          <span
            className="absolute bottom-[-3rem] top-2 w-px bg-primary/22"
            aria-hidden="true"
          />
        ) : null}
        <span
          className={cn(
            "relative mt-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-background transition-colors duration-200",
            selected ? "bg-primary" : "bg-primary/78",
          )}
          aria-hidden="true"
        />
      </div>

      <button
        type="button"
        onClick={(event) => onOpen(event.currentTarget)}
        className={cn(
          "group min-w-0 rounded-mem-md px-1 pb-4 text-left outline-none transition-colors duration-200 [overflow-wrap:anywhere]",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background",
          selected ? "text-foreground" : "hover:text-primary",
        )}
        aria-controls={selected ? "timeline-evidence-drawer" : undefined}
        aria-expanded={selected}
        aria-label={t("timeline.immersive.scene.openEvidenceFor", {
          defaultValue: "查看“{{title}}”的当时记录",
          title,
        })}
      >
        <p className="text-[12px] font-semibold tracking-[0.08em] text-primary">
          {relationLabel} · {sourceLabel(cluster, t)}
        </p>
        <h3 className="mt-4 text-[clamp(1.55rem,2.5vw,2.25rem)] font-semibold leading-[1.24] tracking-[-0.03em] text-foreground">
          {title}
        </h3>
        {body ? (
          <p className="mt-4 max-w-[760px] text-[16px] leading-8 text-foreground/68">{body}</p>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <span className="inline-flex min-h-11 items-center gap-3 rounded-mem-sm bg-card/90 px-4 py-2.5 text-[13px] text-foreground shadow-[0_1px_0_hsl(var(--border)/0.35)]">
            {imageUrl ? (
              <ProtectedImage src={imageUrl} alt="" className="h-8 w-8 rounded-mem-sm object-cover" />
            ) : (
              <span className="flex h-8 w-8 items-center justify-center rounded-mem-sm bg-foreground text-background">
                <SourceIcon sourceType={source} className="h-3.5 w-3.5 text-background" />
              </span>
            )}
            <span>
              <span className="block font-medium">{sourceLabel(cluster, t)}</span>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">
                {t("timeline.immersive.scene.sourceEvidence", {
                  defaultValue: "{{count}} 条原始记录",
                  count: Number(cluster.event_count || 0),
                })}
              </span>
            </span>
          </span>
          <span className="ml-auto inline-flex items-center gap-2 text-[13px] font-medium text-primary">
            {t("timeline.immersive.scene.viewEvidence", {
              defaultValue: "查看当时说了什么",
            })}
            <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
          </span>
        </div>
      </button>
    </article>
  );
};

const EvidenceDrawer: React.FC<{
  cluster: TimelineClusterBlock;
  context: TimelineContextBundle | null;
  loading: boolean;
  failed: boolean;
  onClose: () => void;
}> = ({ cluster, context, loading, failed, onClose }) => {
  const { t } = useTranslation("app");
  const reduceMotion = useReducedMotion();
  const drawerRef = useRef<HTMLElement | null>(null);
  const eventItems = context?.l1_events ?? [];
  const chatItems = context?.chat_excerpts ?? [];
  const chatEventIds = new Set(
    chatItems.map((item) => cleanText(item.event_id)).filter(Boolean),
  );
  const sourceItems = eventItems.filter(
    (item) => !chatEventIds.has(cleanText(item.event_id)),
  );
  const originalChatItems = chatItems.map((item) => {
    const event = eventItems.find(
      (candidate) => cleanText(candidate.event_id) === cleanText(item.event_id),
    );
    return {
      ...event,
      ...item,
      summary: cleanText(item.content) || cleanText(event?.summary),
      source_type: "chat",
    };
  });
  const hasItems = sourceItems.length > 0 || originalChatItems.length > 0;

  useEffect(() => {
    window.requestAnimationFrame(() => drawerRef.current?.focus());
  }, []);

  return (
    <motion.aside
      id="timeline-evidence-drawer"
      ref={drawerRef}
      tabIndex={-1}
      data-testid="timeline-context-drawer"
      role="complementary"
      aria-label={t("timeline.immersive.scene.drawer.title", {
        defaultValue: "当时的记录",
      })}
      initial={{ opacity: 0, x: reduceMotion ? 0 : 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: reduceMotion ? 0 : 24 }}
      transition={{
        duration: reduceMotion ? 0 : 0.32,
        ease: [0.22, 1, 0.36, 1],
      }}
      className="fixed inset-x-4 bottom-4 z-50 max-h-[76vh] overflow-hidden rounded-mem-lg bg-card shadow-[0_24px_70px_hsl(var(--foreground)/0.16)] outline-none lg:inset-x-auto lg:bottom-auto lg:right-6 lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:w-[344px]"
    >
      <div className="flex h-full min-h-0 w-[344px] max-w-full flex-col">
        <header className="flex items-start justify-between gap-4 px-6 pb-5 pt-6">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.12em] text-primary">
              {t("timeline.immersive.scene.drawer.eyebrow", {
                defaultValue: "场景依据",
              })}
            </p>
            <h2 className="mt-2 text-[18px] font-semibold leading-6 tracking-[-0.02em]">
              {sceneTitle(
                cluster,
                t("timeline.immersive.scene.untitledScene", {
                  defaultValue: "一个被留下的片段",
                }),
              )}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-mem-sm text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("timeline.drawer.close", { defaultValue: "关闭上下文面板" })}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-7">
          {loading ? (
            <div className="flex min-h-36 items-center justify-center gap-2 text-[13px] text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("timeline.immersive.scene.drawer.loading", { defaultValue: "正在取回当时的记录" })}
            </div>
          ) : failed ? (
            <p className="rounded-mem-md bg-muted/60 px-4 py-4 text-[13px] leading-6 text-muted-foreground">
              {t("timeline.immersive.scene.drawer.failed", {
                defaultValue: "暂时没能取回这些记录，场景本身仍然保留。",
              })}
            </p>
          ) : hasItems ? (
            <div className="space-y-7">
              {sourceItems.length > 0 ? (
                <EvidenceSection
                  title={t("timeline.immersive.scene.drawer.sourceFacts", {
                    defaultValue: "来源事实",
                  })}
                  items={sourceItems}
                />
              ) : null}
              {originalChatItems.length > 0 ? (
                <EvidenceSection
                  title={t("timeline.immersive.scene.drawer.originalChat", {
                    defaultValue: "原始对话",
                  })}
                  items={originalChatItems}
                  chat
                />
              ) : null}
            </div>
          ) : (
            <p className="rounded-mem-md bg-muted/60 px-4 py-4 text-[13px] leading-6 text-muted-foreground">
              {t("timeline.immersive.scene.drawer.empty", {
                defaultValue: "这个片段目前只有时间、来源和数量，没有可展开的原始内容。",
              })}
            </p>
          )}
        </div>
      </div>
    </motion.aside>
  );
};

const EvidenceSection: React.FC<{
  title: string;
  items: Array<Record<string, unknown>>;
  chat?: boolean;
}> = ({ title, items, chat = false }) => {
  const { t } = useTranslation("app");
  const visibleItems = items.slice(0, 30);
  return (
    <section>
      <h3 className="text-[12px] font-semibold text-muted-foreground">{title}</h3>
      <div className="mt-3 space-y-3">
        {visibleItems.map((item, index) => {
          const timestamp = Number(item.timestamp || 0);
          const source = cleanText(item.source_type) || (chat ? "chat" : "memory");
          const titleText =
            cleanText(item.title) ||
            (chat
              ? t("timeline.immersive.scene.drawer.chatLine", { defaultValue: "对话" })
              : labelForSource(source, t));
          const summary = cleanText(item.summary) || cleanText(item.content);
          return (
            <div
              key={`${cleanText(item.event_id) || titleText}-${index}`}
              className="rounded-mem-md bg-muted/48 px-4 py-3.5"
            >
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <SourceIcon sourceType={source} className="h-3.5 w-3.5" />
                <span>{titleText}</span>
                {timestamp > 0 ? <span className="ml-auto tabular-nums">{formatClock(timestamp)}</span> : null}
              </div>
              {summary ? (
                <p className="mt-2 whitespace-pre-wrap break-words text-[13px] leading-6 text-foreground/76 [overflow-wrap:anywhere]">
                  {summary}
                </p>
              ) : null}
            </div>
          );
        })}
        {items.length > visibleItems.length ? (
          <p className="px-1 text-[11px] leading-5 text-muted-foreground">
            {t("timeline.immersive.scene.drawer.moreItems", {
              defaultValue: "另有 {{count}} 条记录，可在来源中继续查看。",
              count: items.length - visibleItems.length,
            })}
          </p>
        ) : null}
      </div>
    </section>
  );
};

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

  return (
    <section className="mt-16 border-t border-border/55 pt-7">
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
                className="rounded-mem-sm text-[13px] font-medium text-primary outline-none transition-colors hover:text-primary/75 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background"
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
              className="inline-flex items-center gap-2 rounded-mem-sm text-[13px] font-medium text-primary outline-none transition-colors hover:text-primary/75 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background sm:ml-auto"
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
    <article className="group rounded-mem-md bg-muted/46 px-5 py-4 [overflow-wrap:anywhere]">
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
              className="flex h-7 w-7 items-center justify-center rounded-mem-sm outline-none transition-colors hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
              className="flex h-7 w-7 items-center justify-center rounded-mem-sm outline-none transition-colors hover:bg-background hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
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
                className="h-16 w-20 overflow-hidden rounded-mem-sm outline-none transition-opacity hover:opacity-85 focus-visible:ring-2 focus-visible:ring-ring"
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
          className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/82 p-6"
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
