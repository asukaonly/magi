import React, { useEffect, useState } from "react";

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

// ─────────────────────────────────────────────────────────────────────
// Typography variants — temporary A/B/C switcher rendered in the corner
// so the user can compare in-place. Persisted to localStorage. Drop the
// switcher (and the variant map) once we pick a final style.
// ─────────────────────────────────────────────────────────────────────

type HeroVariant = "A" | "B" | "C";
const HERO_VARIANT_STORAGE_KEY = "timeline.heroVariant";
const DEFAULT_HERO_VARIANT: HeroVariant = "A";

interface VariantStyle {
  className: string;
  style: React.CSSProperties;
  description: string;
}

const VARIANT_STYLES: Record<HeroVariant, VariantStyle> = {
  // 沉稳古典 — light weight, relaxed line height, diary-page feel.
  A: {
    className: "m-0 max-w-[640px] text-[24px] font-light leading-[1.7]",
    style: {
      fontFamily:
        '"Source Han Serif SC", "Songti SC", "Noto Serif SC", "PingFang SC", serif',
      letterSpacing: "0.04em",
      opacity: 0.94,
    },
    description: "沉稳古典 24px / light",
  },
  // 明亮诗意 — slightly larger, softer glow for readability over photos.
  B: {
    className: "m-0 max-w-[640px] text-[30px] font-normal leading-[1.55]",
    style: {
      fontFamily:
        '"Source Han Serif SC", "Songti SC", "Noto Serif SC", "PingFang SC", serif',
      letterSpacing: "0.02em",
      textShadow: "0 2px 12px rgba(0,0,0,0.25)",
    },
    description: "明亮诗意 30px / normal",
  },
  // 大字仪式感 — narrow column, big type, more reading rhythm.
  C: {
    className: "m-0 max-w-[480px] text-[36px] font-medium leading-[1.4]",
    style: {
      fontFamily:
        '"Source Han Serif SC", "Songti SC", "Noto Serif SC", "PingFang SC", serif',
      letterSpacing: "0.01em",
    },
    description: "大字仪式感 36px / medium",
  },
};

function readStoredVariant(): HeroVariant {
  if (typeof window === "undefined") return DEFAULT_HERO_VARIANT;
  try {
    const stored = window.localStorage.getItem(HERO_VARIANT_STORAGE_KEY);
    if (stored === "A" || stored === "B" || stored === "C") return stored;
  } catch {
    /* localStorage unavailable (private mode etc.) */
  }
  return DEFAULT_HERO_VARIANT;
}

/** TEMPORARY: small corner pill that switches the essence typography variant.
 *  Remove once we commit to a final style. */
const VariantSwitcher: React.FC<{
  current: HeroVariant;
  onChange: (next: HeroVariant) => void;
}> = ({ current, onChange }) => {
  return (
    <div className="absolute right-3 top-3 z-20 flex items-center gap-0.5 rounded-full bg-black/30 p-0.5 backdrop-blur-sm">
      {(["A", "B", "C"] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          title={VARIANT_STYLES[v].description}
          className={cn(
            "h-6 w-6 rounded-full text-[11px] font-medium leading-none transition-colors",
            current === v
              ? "bg-white/90 text-black/85"
              : "text-white/80 hover:bg-white/15",
          )}
        >
          {v}
        </button>
      ))}
    </div>
  );
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
  const [variant, setVariant] = useState<HeroVariant>(DEFAULT_HERO_VARIANT);

  // Read persisted choice after mount (avoid SSR mismatch / Tauri startup
  // localStorage hiccups).
  useEffect(() => {
    setVariant(readStoredVariant());
  }, []);

  const handleVariantChange = (next: HeroVariant) => {
    setVariant(next);
    try {
      window.localStorage.setItem(HERO_VARIANT_STORAGE_KEY, next);
    } catch {
      /* ignore quota / unavailable */
    }
  };

  const variantStyle = VARIANT_STYLES[variant];

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

      <VariantSwitcher current={variant} onChange={handleVariantChange} />

      <div className="absolute inset-x-0 bottom-0 z-10 px-10 pb-8 text-white">
        <div className="mb-3 text-[10px] uppercase tracking-[0.28em] opacity-80">
          {dateLabel}
        </div>
        {essenceProse && (
          <h2 className={variantStyle.className} style={variantStyle.style}>
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
