import React from "react";

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
  className,
}) => {
  const hasPhoto = Boolean(photoUrl);

  return (
    <div
      className={cn(
        "relative h-[280px] overflow-hidden",
        !hasPhoto && TONE_GRADIENTS[fallbackTone],
        className
      )}
    >
      {hasPhoto && photoUrl && (
        <img
          src={photoUrl}
          alt="hero photo"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}

      {hasPhoto && (
        <div className="absolute inset-0 bg-gradient-to-b from-black/15 via-black/25 to-black/75" />
      )}

      <div className="absolute inset-x-0 bottom-0 z-10 px-10 pb-8 text-white">
        <div className="mb-3 text-[10px] uppercase tracking-[0.28em] opacity-80">
          {dateLabel}
        </div>
        {essenceProse && (
          // Variant A — "沉稳古典". Light weight + relaxed line height + the
          // Songti/Source Han Serif fall-through give the essence a diary-page
          // feel rather than a headline shout.
          <h2
            className="m-0 max-w-[640px] text-[24px] font-light leading-[1.7]"
            style={{
              fontFamily:
                '"Source Han Serif SC", "Songti SC", "Noto Serif SC", "PingFang SC", serif',
              letterSpacing: "0.04em",
              opacity: 0.94,
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
