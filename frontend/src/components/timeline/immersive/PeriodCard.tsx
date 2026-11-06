import React, { useMemo, useState } from "react";

import type {
  TimelineCoverCandidate,
  TimelineCoverState,
  TimelineViewportResponse,
  TimelineReviewPeriod,
  TimelineStandoutItem,
} from "@/api/modules/timeline";
import type { ManualEntry } from "@/api/modules/manualEntries";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

import { CoverPickerSheet, type TimelineCoverChangeRequest } from "./CoverPickerSheet";
import { DaySceneReader } from "./DaySceneReader";
import { PeriodReviewReader } from "./PeriodReviewReader";

interface PeriodCardProps {
  scale: "month" | "week" | "day" | "hour";
  viewport: TimelineViewportResponse;
  dateLabel: string;
  placeLine?: string;
  onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>;
  onHide: (episodeId: string) => void | Promise<void>;
  pendingAction: Record<string, "pin" | "hide" | null>;
  /** Used by the week strip to drill into a single day. ISO date "YYYY-MM-DD". */
  onSelectDay?: (isoDate: string) => void;
  /** Manual user-authored memory entries for this window. Day-scale renders
   *  them as a dedicated "你的记录" group at the top of each time bucket. */
  manualEntries?: ManualEntry[];
  onEditManualEntry?: (entry: ManualEntry) => void;
  onDeleteManualEntry?: (entryId: string) => void;
  onChangeCover?: (payload: TimelineCoverChangeRequest) => void | Promise<void>;
  onUploadCover?: (file: File) => Promise<string>;
  coverSaving?: boolean;
  onOpenExperience?: (experienceId: string) => void;
  onOrganizeExperience?: () => void;
  onAddNote?: () => void;
  onSelectPeriod?: (period: TimelineReviewPeriod) => void;
  standoutItems?: TimelineStandoutItem[];
  onSelectStandout?: (item: TimelineStandoutItem) => void;
  selectedTopic?: string;
  onSelectTopic?: (topic: string) => void;
}

function pickHeroAssetRef(viewport: TimelineViewportResponse): string | null {
  if (viewport.cover?.mode === "hidden") return null;
  if (viewport.cover?.asset_ref) return viewport.cover.asset_ref;

  // Prefer user-pinned clusters, then longer episodes.
  const ranked = [...(viewport.clusters || [])].sort((a, b) => {
    if (a.user_pinned !== b.user_pinned) return a.user_pinned ? -1 : 1;
    return (b.time_end - b.time_start) - (a.time_end - a.time_start);
  });
  for (const cluster of ranked) {
    const ref = String(cluster.representative_asset_ref || "").trim();
    if (ref) return ref;
  }
  return null;
}

function clusterCoverCandidates(viewport: TimelineViewportResponse): TimelineCoverCandidate[] {
  const ranked = [...(viewport.clusters || [])].sort((a, b) => {
    if (a.user_pinned !== b.user_pinned) return a.user_pinned ? -1 : 1;
    return (b.time_end - b.time_start) - (a.time_end - a.time_start);
  });
  const candidates: TimelineCoverCandidate[] = [];
  const seen = new Set<string>();
  for (const cluster of ranked) {
    const ref = String(cluster.representative_asset_ref || "").trim();
    if (!ref || seen.has(ref)) continue;
    seen.add(ref);
    candidates.push({
      asset_ref: ref,
      source: "current_period",
      label: cluster.slice_narrative || cluster.summary || cluster.label || "",
      cluster_id: cluster.block_id,
      episode_id: cluster.episode_id ?? null,
    });
  }
  return candidates;
}

function resolveCoverForPicker(viewport: TimelineViewportResponse): TimelineCoverState {
  const fallbackCandidates = clusterCoverCandidates(viewport);
  const cover = viewport.cover;
  const coverCandidates = cover?.candidates ?? [];
  const mergedCandidates = coverCandidates.length > 0 ? [...coverCandidates] : [...fallbackCandidates];
  const assetRef = cover?.asset_ref ?? null;
  if (assetRef && !mergedCandidates.some((candidate) => candidate.asset_ref === assetRef)) {
    mergedCandidates.unshift({
      asset_ref: assetRef,
      source: cover?.source || "current_period",
      label: "",
      cluster_id: null,
      episode_id: null,
    });
  }

  const mode = cover?.mode ?? "auto";
  return {
    mode,
    asset_ref: mode === "hidden" ? null : assetRef || fallbackCandidates[0]?.asset_ref || null,
    source: cover?.source ?? "auto",
    candidates: mergedCandidates,
  };
}

export const PeriodCard: React.FC<PeriodCardProps> = ({
  scale,
  viewport,
  dateLabel,
  placeLine,
  manualEntries,
  onEditManualEntry,
  onDeleteManualEntry,
  onChangeCover,
  onUploadCover,
  coverSaving = false,
  onOpenExperience,
  onOrganizeExperience,
  onAddNote,
  onSelectPeriod, standoutItems, onSelectStandout, selectedTopic = "", onSelectTopic = () => {},
}) => {
  const [coverSheetOpen, setCoverSheetOpen] = useState(false);
  const heroAssetRef = useMemo(() => pickHeroAssetRef(viewport), [viewport]);
  const coverForPicker = useMemo(() => resolveCoverForPicker(viewport), [viewport]);
  const photoUrl = useMemo(() => resolveTimelineAssetUrl(heroAssetRef), [heroAssetRef]);
  // place_hints from the LocationResolver — primary chip on top, optional
  // secondary chips appended with a thin separator. Caller-provided
  // placeLine still wins so manual overrides remain possible.
  const resolvedPlaceLine = (() => {
    if (placeLine) return placeLine;
    const hints = viewport.place_hints ?? [];
    if (hints.length === 0) return undefined;
    if (hints.length === 1) return hints[0];
    return `${hints[0]} · ${hints.slice(1, 3).join(" · ")}`;
  })();

  if (scale === "day") {
    return (
      <div className="bg-background">
        <DaySceneReader
          viewport={viewport}
          dateLabel={dateLabel}
          placeLine={resolvedPlaceLine}
          coverUrl={photoUrl}
          manualEntries={manualEntries ?? []}
          onOpenExperience={onOpenExperience}
          onOrganizeExperience={onOrganizeExperience}
          onAddNote={onAddNote}
          onEditManualEntry={onEditManualEntry}
          onDeleteManualEntry={onDeleteManualEntry}
          onOpenCover={onChangeCover ? () => setCoverSheetOpen(true) : undefined}
        />
        {onChangeCover ? (
          <CoverPickerSheet
            open={coverSheetOpen}
            cover={coverForPicker}
            onOpenChange={setCoverSheetOpen}
            onChangeCover={onChangeCover}
            onUploadCover={onUploadCover}
            saving={coverSaving}
          />
        ) : null}
      </div>
    );
  }

  return <div className="bg-background">
    <PeriodReviewReader scale={scale === 'month' ? 'month' : 'week'} viewport={viewport} dateLabel={dateLabel}
      coverUrl={photoUrl} onSelectPeriod={onSelectPeriod} onAddNote={onAddNote} onOpenCover={onChangeCover ? () => setCoverSheetOpen(true) : undefined}
      standoutItems={standoutItems} onSelectStandout={onSelectStandout} selectedTopic={selectedTopic} onSelectTopic={onSelectTopic} />
    {onChangeCover ? <CoverPickerSheet open={coverSheetOpen} cover={coverForPicker} onOpenChange={setCoverSheetOpen}
      onChangeCover={onChangeCover} onUploadCover={onUploadCover} saving={coverSaving} /> : null}
  </div>;
};
