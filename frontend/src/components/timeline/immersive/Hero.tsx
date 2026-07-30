import React from "react";

import { ProtectedImage } from "@/components/media/ProtectedImage";
import { cn } from "@/lib/utils";

export type HeroFallbackTone =
  | "warm"
  | "cool"
  | "neutral"
  | "bright"
  | "tense";

interface HeroProps {
  dateLabel: string;
  essenceProse: string;
  placeLine?: string;
  photoUrl: string | null;
  fallbackTone?: HeroFallbackTone;
  action?: React.ReactNode;
  className?: string;
}

const TONE_GRADIENTS: Record<HeroFallbackTone, string> = {
  warm: "bg-gradient-to-br from-[#d4b886] via-[#c9a878] to-[#8a7a5a]",
  bright: "bg-gradient-to-br from-[#e8d3a0] via-[#d4b886] to-[#a89070]",
  neutral: "bg-gradient-to-br from-[#c2bba8] via-[#a8a08a] to-[#8a8275]",
  cool: "bg-gradient-to-br from-[#a8b4c2] via-[#7a8898] to-[#5a6878]",
  tense: "bg-gradient-to-br from-[#c2a098] via-[#b87a78] to-[#8a5050]",
};

export const Hero: React.FC<HeroProps> = ({
  dateLabel,
  essenceProse,
  placeLine,
  photoUrl,
  fallbackTone = "neutral",
  action,
  className,
}) => {
  const hasPhoto = Boolean(photoUrl);

  return (
    <div
      className={cn(
        // min-h instead of fixed h — when the essence is long the container
        // grows downward to fit. With the previous fixed h-[280px] the absolute-
        // positioned text block could overflow upward past the date label and
        // be clipped by overflow-hidden, hiding the "2026 年 5 月 18 日 周一"
        // header on dense days.
        "relative flex min-h-[280px] flex-col justify-end overflow-hidden",
        !hasPhoto && TONE_GRADIENTS[fallbackTone],
        className
      )}
    >
      {hasPhoto && photoUrl && (
        <ProtectedImage
          src={photoUrl}
          alt="hero photo"
          eager
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}

      {hasPhoto && (
        <div className="absolute inset-0 bg-gradient-to-b from-black/15 via-black/25 to-black/75" />
      )}

      {action && <div className="absolute right-4 top-4 z-20">{action}</div>}

      {/* Normal-flow text block (no longer absolute) so its height
          contributes to the container — Hero grows with essence length.
          pt-12 keeps the date label off the top edge even when the
          container has expanded; pb-8 keeps the place line off the bottom. */}
      <div className="relative z-10 px-10 pb-8 pt-12 text-white">
        <div className="mb-3 text-[10px] uppercase tracking-[0.28em] opacity-80">
          {dateLabel}
        </div>
        {essenceProse && (
          // Typography "明亮诗意": Source Han Serif at 30px / normal weight /
          // 1.55 line-height. Soft text-shadow gives readability on both photo
          // backgrounds and abstract gradients without making the text feel
          // boxed-in.
          <h2
            className="m-0 max-w-[640px] text-[30px] font-normal leading-[1.55]"
            style={{
              fontFamily:
                '"Source Han Serif SC", "Songti SC", "Noto Serif SC", "PingFang SC", serif',
              letterSpacing: "0.02em",
              textShadow: "0 2px 12px rgba(0,0,0,0.25)",
            }}
          >
            {essenceProse}
          </h2>
        )}
        {placeLine && (
          <div className="mt-3 flex items-center gap-1.5 text-xs opacity-70">
            <span className="text-base">◦</span>
            <span>{placeLine}</span>
          </div>
        )}
      </div>
    </div>
  );
};
