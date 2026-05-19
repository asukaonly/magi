import React from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type ToolbarScale = "month" | "week" | "day" | "hour";

interface ToolbarProps {
  scale: ToolbarScale;
  dateLabel: string;
  draftQuery: string;
  canGoNext: boolean;
  onScaleChange: (next: ToolbarScale) => void;
  onPrevious: () => void;
  onNext: () => void;
  onDraftQueryChange: (next: string) => void;
  onSubmitQuery: () => void;
  onRefresh: () => void;
}

const SCALE_LABEL: Record<ToolbarScale, string> = {
  month: "月",
  week: "周",
  day: "日",
  hour: "时",
};

export const Toolbar: React.FC<ToolbarProps> = ({
  scale,
  dateLabel,
  draftQuery,
  canGoNext,
  onScaleChange,
  onPrevious,
  onNext,
  onDraftQueryChange,
  onSubmitQuery,
  onRefresh,
}) => {
  const { t } = useTranslation("app");

  return (
    <div className="flex h-12 items-center gap-4 border-b border-border/40 bg-background px-6">
      <h1 className="text-sm font-semibold text-foreground">
        {t("timeline.title", { defaultValue: "时间线" })}
      </h1>
      <span className="text-xs text-muted-foreground">{dateLabel}</span>

      <div className="flex-1" />

      <div className="flex rounded-md bg-foreground/5 p-0.5">
        {(Object.keys(SCALE_LABEL) as ToolbarScale[]).map((s) => (
          <button
            key={s}
            type="button"
            aria-label={SCALE_LABEL[s]}
            data-active={s === scale ? "true" : "false"}
            onClick={() => onScaleChange(s)}
            className={cn(
              "rounded-sm px-2.5 py-1 text-xs",
              s === scale
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {SCALE_LABEL[s]}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("timeline.previousPeriod", { defaultValue: "上一段" })}
          onClick={onPrevious}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5"
        >
          ‹
        </button>
        <button
          type="button"
          aria-label={t("timeline.nextPeriod", { defaultValue: "下一段" })}
          onClick={onNext}
          disabled={!canGoNext}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5 disabled:cursor-not-allowed disabled:opacity-30"
        >
          ›
        </button>
      </div>

      <Input
        value={draftQuery}
        onChange={(e) => onDraftQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmitQuery();
        }}
        placeholder={t("timeline.searchPlaceholder", { defaultValue: "筛选当前时段" })}
        className="h-7 w-48 text-xs"
      />

      <button
        type="button"
        aria-label={t("timeline.refresh", { defaultValue: "刷新" })}
        onClick={onRefresh}
        className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5"
      >
        ↻
      </button>
    </div>
  );
};
