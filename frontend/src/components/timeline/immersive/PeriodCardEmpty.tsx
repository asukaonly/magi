import React from "react";
import { useTranslation } from "react-i18next";

import { EmptyStateAvailableSources } from "../../empty-state/EmptyStateAvailableSources";

interface PeriodCardEmptyProps {
  scale: "month" | "week" | "day" | "hour";
  dateLabel: string;
}

export const PeriodCardEmpty: React.FC<PeriodCardEmptyProps> = ({ scale, dateLabel }) => {
  const { t } = useTranslation("app");
  const emptyMessage =
    scale === "month"
      ? t("timeline.immersive.emptyMonth", {
          defaultValue: "月度回顾需要几周时间慢慢长出来。先从日开始翻？",
        })
      : t("timeline.immersive.emptyDay", {
          defaultValue: "再陪你几天，这页就会写满你的样子。",
        });

  return (
    <div className="flex min-h-[400px] flex-col items-center justify-center gap-3 px-10 py-10 text-center">
      <div className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
        {dateLabel}
      </div>
      <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">
        {emptyMessage}
      </p>
      <div className="mt-8 w-full max-w-3xl">
        <EmptyStateAvailableSources i18nNamespace="app" i18nKeyPrefix="timeline" />
      </div>
    </div>
  );
};
