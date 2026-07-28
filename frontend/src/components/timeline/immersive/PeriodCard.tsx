import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Image } from "lucide-react";

import type {
  TimelineCoverCandidate,
  TimelineCoverState,
  TimelineViewportResponse,
} from "@/api/modules/timeline";
import type { ManualEntry } from "@/api/modules/manualEntries";
import { Button } from "@/components/ui/button";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

import { CoverPickerSheet, type TimelineCoverChangeRequest } from "./CoverPickerSheet";
import { DaySceneReader } from "./DaySceneReader";
import { Hero, type HeroFallbackTone } from "./Hero";
import { PeriodCardEmpty } from "./PeriodCardEmpty";
import { Slice } from "./Slice";
import { StateBand } from "./StateBand";
import { ThemesRow } from "./ThemesRow";
import { WeekStrip } from "./WeekStrip";

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
}

function formatTimeRange(startSec: number, endSec: number): string {
  const fmt = (s: number) => {
    const d = new Date(s * 1000);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  };
  return `${fmt(startSec)} – ${fmt(endSec)}`;
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

function valenceToFallbackTone(dominant: string | undefined): HeroFallbackTone {
  const allowed: HeroFallbackTone[] = ["warm", "cool", "neutral", "bright", "tense"];
  if (dominant && (allowed as string[]).includes(dominant)) return dominant as HeroFallbackTone;
  return "neutral";
}

export const PeriodCard: React.FC<PeriodCardProps> = ({
  scale,
  viewport,
  dateLabel,
  placeLine,
  onTogglePinned,
  onHide,
  pendingAction,
  onSelectDay,
  manualEntries,
  onEditManualEntry,
  onDeleteManualEntry,
  onChangeCover,
  onUploadCover,
  coverSaving = false,
  onOpenExperience,
  onOrganizeExperience,
  onAddNote,
}) => {
  const { t } = useTranslation("app");
  const [coverSheetOpen, setCoverSheetOpen] = useState(false);
  const hasContent =
    (viewport.clusters?.length ?? 0) > 0 ||
    (viewport.summary?.event_count ?? 0) > 0 ||
    (viewport.overview?.essence_prose ?? "").length > 0 ||
    (scale === "day" && (manualEntries?.some((entry) => !entry.deleted_at) ?? false));

  const heroAssetRef = useMemo(() => pickHeroAssetRef(viewport), [viewport]);
  const coverForPicker = useMemo(() => resolveCoverForPicker(viewport), [viewport]);
  const photoUrl = useMemo(() => resolveTimelineAssetUrl(heroAssetRef), [heroAssetRef]);
  // state_summary in the real type uses mood_label etc., but callers may pass
  // a dominant_valence field (Plan 3 backend extension). Access via unknown cast.
  const dominantValence = (viewport.state_summary as unknown as Record<string, unknown>)?.dominant_valence as string | undefined;
  const fallbackTone = valenceToFallbackTone(dominantValence);
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

  if (!hasContent) {
    return <PeriodCardEmpty scale={scale} dateLabel={dateLabel} />;
  }

  return (
    <div className="bg-background">
      <Hero
        dateLabel={dateLabel}
        essenceProse={viewport.overview?.essence_prose ?? ""}
        placeLine={resolvedPlaceLine}
        photoUrl={photoUrl}
        fallbackTone={fallbackTone}
        action={
          onChangeCover ? (
            <Button
              type="button"
              size="icon"
              variant="secondary"
              aria-label={t("timeline.cover.open", { defaultValue: "更换封面" })}
              title={t("timeline.cover.open", { defaultValue: "更换封面" })}
              onClick={() => setCoverSheetOpen(true)}
              className="bg-background/80 text-foreground shadow-sm backdrop-blur hover:bg-background"
            >
              <Image className="h-4 w-4" />
            </Button>
          ) : null
        }
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
      <StateBand
        bands={viewport.state_bands ?? []}
        periodStart={viewport.viewport.start}
        periodEnd={viewport.viewport.end}
      />
      <ThemesRow themes={viewport.theme_cards ?? []} />
      {scale === "week" ? (
        <WeekStrip
          clusters={viewport.clusters ?? []}
          weekStart={viewport.viewport.start}
          onSelectDay={(iso) => onSelectDay?.(iso)}
        />
      ) : (
        // Month scale: keep the original slice list (cluster-per-day rollups
        // from L2 episodes already feel right at this granularity, and we
        // don't have a richer treatment yet).
        <div className="px-10 pb-7 pt-2">
          {(viewport.clusters ?? []).map((cluster) => (
            <Slice
              key={cluster.block_id}
              episodeId={cluster.episode_id ?? ""}
              timeRangeLabel={formatTimeRange(cluster.time_start, cluster.time_end)}
              narrative={cluster.slice_narrative || cluster.summary || cluster.label || ""}
              sensoryDetail={cluster.slice_sensory_detail || undefined}
              isPinned={Boolean(cluster.user_pinned)}
              onTogglePinned={onTogglePinned}
              onHide={onHide}
              pendingAction={pendingAction[cluster.episode_id ?? ""] ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
};
