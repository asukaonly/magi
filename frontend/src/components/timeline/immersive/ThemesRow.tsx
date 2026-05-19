import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineThemeCard } from "@/api/modules/timeline";

interface ThemesRowProps {
  themes: TimelineThemeCard[];
  maxThemes?: number;
}

export const ThemesRow: React.FC<ThemesRowProps> = ({ themes, maxThemes = 4 }) => {
  const { t } = useTranslation("app");
  const visible = themes.slice(0, maxThemes);

  if (visible.length === 0) return null;

  return (
    <div className="flex flex-wrap items-baseline gap-3 px-10 pt-5 pb-1">
      <span className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {t("timeline.immersive.themesLabel", { defaultValue: "你那时关心的" })}
      </span>
      {visible.map((theme) => (
        <span
          key={theme.theme_id}
          className="border-b border-dotted border-muted-foreground/40 pb-[1px] text-[13.5px] text-foreground"
        >
          {theme.title}
        </span>
      ))}
    </div>
  );
};
