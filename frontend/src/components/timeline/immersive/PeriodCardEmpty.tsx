import React from "react";
import { useTranslation } from "react-i18next";

import { EmptyStateAvailableSensors } from "../../empty-state/EmptyStateAvailableSensors";

interface PeriodCardEmptyProps {
  scale: "month" | "week" | "day" | "hour";
  dateLabel: string;
}

export const PeriodCardEmpty: React.FC<PeriodCardEmptyProps> = ({ scale, dateLabel }) => {
  const { t } = useTranslation("app");
  const emptyMessage =
    scale === "month"
      ? t("timeline.immersive.emptyMonth", {
          defaultValue: "A monthly review needs a few weeks to grow. Start with a day?",
        })
      : t("timeline.immersive.emptyDay", {
          defaultValue: "Give it a few more days and this page will fill in with you.",
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
        <EmptyStateAvailableSensors />
      </div>
    </div>
  );
};
