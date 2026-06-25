import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, EyeOff, Image, RotateCcw } from "lucide-react";

import type {
  TimelineCoverCandidate,
  TimelineCoverMode,
  TimelineCoverState,
} from "@/api/modules/timeline";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

export interface TimelineCoverChangeRequest {
  mode: TimelineCoverMode;
  asset_ref?: string | null;
  source?: string;
}

interface CoverPickerSheetProps {
  open: boolean;
  cover?: TimelineCoverState;
  onOpenChange: (open: boolean) => void;
  onChangeCover: (payload: TimelineCoverChangeRequest) => void | Promise<void>;
  saving?: boolean;
}

function candidateLabel(candidate: TimelineCoverCandidate, index: number, fallback: string): string {
  const label = String(candidate.label || "").trim();
  return label || `${fallback} ${index + 1}`;
}

export const CoverPickerSheet: React.FC<CoverPickerSheetProps> = ({
  open,
  cover,
  onOpenChange,
  onChangeCover,
  saving = false,
}) => {
  const { t } = useTranslation("app");
  const candidates = cover?.candidates ?? [];
  const fallbackLabel = t("timeline.cover.candidate", { defaultValue: "图片" });
  const [selectedRef, setSelectedRef] = useState<string | null>(cover?.asset_ref ?? null);

  useEffect(() => {
    if (!open) return;
    setSelectedRef(cover?.asset_ref ?? candidates[0]?.asset_ref ?? null);
  }, [candidates, cover?.asset_ref, open]);

  const selectedCandidate = useMemo(
    () => candidates.find((candidate) => candidate.asset_ref === selectedRef) ?? null,
    [candidates, selectedRef]
  );

  const handleUseSelected = async () => {
    if (!selectedCandidate) return;
    await onChangeCover({
      mode: "asset",
      asset_ref: selectedCandidate.asset_ref,
      source: selectedCandidate.source || "current_period",
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] max-w-[92vw] flex-col overflow-hidden p-0">
        <SheetHeader className="border-b border-border/70 px-6 pb-4 pt-6">
          <SheetTitle>{t("timeline.cover.title", { defaultValue: "更换封面" })}</SheetTitle>
          <SheetDescription className="sr-only">
            {t("timeline.cover.description", { defaultValue: "Timeline cover settings" })}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-4 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Image className="h-3.5 w-3.5" />
            <span>{t("timeline.cover.currentPeriod", { defaultValue: "当前周期" })}</span>
          </div>

          {candidates.length > 0 ? (
            <div className="grid grid-cols-2 gap-3">
              {candidates.map((candidate, index) => {
                const label = candidateLabel(candidate, index, fallbackLabel);
                const url = resolveTimelineAssetUrl(candidate.asset_ref);
                const selected = candidate.asset_ref === selectedRef;
                return (
                  <button
                    key={`${candidate.asset_ref}-${index}`}
                    type="button"
                    aria-label={label}
                    onClick={() => setSelectedRef(candidate.asset_ref)}
                    className={cn(
                      "group relative aspect-[4/3] overflow-hidden rounded-md bg-muted text-left",
                      "shadow-[inset_0_0_0_1px_hsl(var(--border)/0.65)] transition",
                      selected && "shadow-[inset_0_0_0_2px_hsl(var(--primary))]"
                    )}
                  >
                    {url ? (
                      <img src={url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                        <Image className="h-5 w-5" />
                      </div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2 pb-2 pt-8">
                      <div className="line-clamp-2 text-xs leading-snug text-white">{label}</div>
                    </div>
                    {selected && (
                      <div className="absolute right-2 top-2 rounded-full bg-background p-1 text-foreground shadow-sm">
                        <Check className="h-3.5 w-3.5" />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex min-h-[180px] items-center justify-center rounded-md border border-dashed border-border/70 text-sm text-muted-foreground">
              {t("timeline.cover.empty", { defaultValue: "这个周期暂时没有可用图片" })}
            </div>
          )}
        </div>

        <SheetFooter className="grid grid-cols-[1fr_1fr] gap-2 px-6 py-4 sm:flex sm:justify-between">
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChangeCover({ mode: "auto" })}
              disabled={saving}
            >
              <RotateCcw className="h-4 w-4" />
              {t("timeline.cover.restoreAuto", { defaultValue: "恢复自动" })}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChangeCover({ mode: "hidden" })}
              disabled={saving}
            >
              <EyeOff className="h-4 w-4" />
              {t("timeline.cover.hide", { defaultValue: "隐藏封面" })}
            </Button>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={handleUseSelected}
            disabled={!selectedCandidate || saving}
          >
            <Check className="h-4 w-4" />
            {t("timeline.cover.useSelected", { defaultValue: "设为封面" })}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
};
