import React from "react";

import type { TimelineStateBand } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";

interface StateBandProps {
  bands: TimelineStateBand[];
  periodStart: number;
  periodEnd: number;
  className?: string;
}

const VALENCE_COLOR: Record<string, string> = {
  warm: "#c9a878",
  bright: "#d4b886",
  neutral: "#a8a08a",
  cool: "#7a8898",
  tense: "#b87a78",
};

function valenceToColor(valence: number): string {
  if (valence >= 0.60) return VALENCE_COLOR.bright;
  if (valence >= 0.20) return VALENCE_COLOR.warm;
  if (valence >= -0.20) return VALENCE_COLOR.neutral;
  if (valence >= -0.50) return VALENCE_COLOR.cool;
  return VALENCE_COLOR.tense;
}

export const StateBand: React.FC<StateBandProps> = ({
  bands,
  periodStart,
  periodEnd,
  className,
}) => {
  const duration = periodEnd - periodStart;
  if (duration <= 0 || bands.length === 0) {
    return <div className={cn("h-1.5 bg-[#e8e3d8]", className)} aria-hidden="true" />;
  }

  // Build a linear gradient where each band occupies a slice proportional to its duration.
  const stops: string[] = [];
  let cursor = 0;
  for (const band of bands) {
    const start = Math.max(0, ((band.time_start - periodStart) / duration) * 100);
    const end = Math.min(100, ((band.time_end - periodStart) / duration) * 100);
    const color = valenceToColor(band.valence);
    stops.push(`${color} ${start.toFixed(1)}%`);
    stops.push(`${color} ${end.toFixed(1)}%`);
    cursor = end;
  }
  if (cursor < 100) {
    const last = stops[stops.length - 1]?.split(" ")[0] ?? VALENCE_COLOR.neutral;
    stops.push(`${last} ${cursor.toFixed(1)}%`);
    stops.push(`${last} 100%`);
  }
  const background = `linear-gradient(90deg, ${stops.join(", ")})`;

  return (
    <div
      className={cn("h-1.5", className)}
      style={{ background }}
      aria-hidden="true"
    />
  );
};
