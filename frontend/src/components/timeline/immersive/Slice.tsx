import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface SliceProps {
  episodeId: string;
  timeRangeLabel: string;
  narrative: string;
  sensoryDetail?: string;
  isPinned: boolean;
  onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>;
  onHide: (episodeId: string) => void | Promise<void>;
  pendingAction?: "pin" | "hide" | null;
}

export const Slice: React.FC<SliceProps> = ({
  episodeId,
  timeRangeLabel,
  narrative,
  sensoryDetail,
  isPinned,
  onTogglePinned,
  onHide,
  pendingAction,
}) => {
  const { t } = useTranslation("app");
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="group grid grid-cols-[110px_1fr_auto] items-baseline gap-7 border-b border-border/30 py-5 last:border-b-0">
      <div className="font-mono text-xs uppercase tracking-[0.1em] text-muted-foreground">
        {timeRangeLabel}
      </div>

      <div className="max-w-[640px] text-[15.5px] leading-[1.85] text-foreground">
        {narrative}
        {sensoryDetail && (
          <span className="mt-1.5 block text-[12.5px] italic text-muted-foreground">
            {sensoryDetail}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-label={t("timeline.immersive.heartLabel", { defaultValue: "Worth coming back to" })}
          data-pinned={isPinned ? "true" : "false"}
          disabled={pendingAction === "pin"}
          onClick={() => onTogglePinned(episodeId, !isPinned)}
          className={cn(
            "text-lg transition-opacity",
            isPinned
              ? "text-[#b87a78] opacity-100"
              : "text-muted-foreground/40 opacity-0 group-hover:opacity-100 hover:text-[#b87a78]"
          )}
        >
          ♡
        </button>

        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label={t("timeline.immersive.moreLabel", { defaultValue: "More" })}
              className="text-muted-foreground/40 opacity-0 group-hover:opacity-100"
            >
              ⋯
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={pendingAction === "hide"}
              onSelect={() => {
                setMenuOpen(false);
                void onHide(episodeId);
              }}
            >
              {t("timeline.immersive.hideMemoryLabel", { defaultValue: "Do not count toward this day" })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
};
