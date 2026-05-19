import React, { useMemo } from "react";

import type { TimelineViewportResponse } from "@/api/modules/timeline";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

import { Hero, type HeroFallbackTone } from "./Hero";
import { PeriodCardEmpty } from "./PeriodCardEmpty";
import { Slice } from "./Slice";
import { StateBand } from "./StateBand";
import { ThemesRow } from "./ThemesRow";

interface PeriodCardProps {
  scale: "month" | "week" | "day" | "hour";
  viewport: TimelineViewportResponse;
  dateLabel: string;
  placeLine?: string;
  onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>;
  onHide: (episodeId: string) => void | Promise<void>;
  pendingAction: Record<string, "pin" | "hide" | null>;
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

function pickHeroPhotoUrl(viewport: TimelineViewportResponse): string | null {
  // Prefer user-pinned clusters, then longer episodes.
  const ranked = [...(viewport.clusters || [])].sort((a, b) => {
    if (a.user_pinned !== b.user_pinned) return a.user_pinned ? -1 : 1;
    return (b.time_end - b.time_start) - (a.time_end - a.time_start);
  });
  for (const cluster of ranked) {
    const url = resolveTimelineAssetUrl(cluster.representative_asset_ref);
    if (url) return url;
  }
  return null;
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
}) => {
  const hasContent =
    (viewport.clusters?.length ?? 0) > 0 ||
    (viewport.summary?.event_count ?? 0) > 0 ||
    (viewport.overview?.essence_prose ?? "").length > 0;

  const photoUrl = useMemo(() => pickHeroPhotoUrl(viewport), [viewport]);
  // state_summary in the real type uses mood_label etc., but callers may pass
  // a dominant_valence field (Plan 3 backend extension). Access via unknown cast.
  const dominantValence = (viewport.state_summary as unknown as Record<string, unknown>)?.dominant_valence as string | undefined;
  const fallbackTone = valenceToFallbackTone(dominantValence);

  if (!hasContent) {
    return <PeriodCardEmpty scale={scale} dateLabel={dateLabel} />;
  }

  return (
    <div className="bg-background">
      <Hero
        dateLabel={dateLabel}
        essenceProse={viewport.overview?.essence_prose ?? ""}
        placeLine={placeLine}
        photoUrl={photoUrl}
        fallbackTone={fallbackTone}
      />
      <StateBand
        bands={viewport.state_bands ?? []}
        periodStart={viewport.viewport.start}
        periodEnd={viewport.viewport.end}
      />
      <ThemesRow themes={viewport.theme_cards ?? []} />
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
    </div>
  );
};
