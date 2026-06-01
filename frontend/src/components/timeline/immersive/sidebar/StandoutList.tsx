import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineStandoutItem } from "@/api/modules/timeline";

interface StandoutListProps {
  items: TimelineStandoutItem[];
  onSelectEpisode: (episodeId: string) => void;
}

export const StandoutList: React.FC<StandoutListProps> = ({ items, onSelectEpisode }) => {
  const { t } = useTranslation("app");

  return (
    <div className="border-t border-border/30 px-4 py-4">
      <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {t("timeline.immersive.standoutLabel", { defaultValue: "值得回来的" })}
      </div>
      {items.length === 0 ? (
        <p className="text-[12px] italic text-muted-foreground/70 leading-relaxed">
          {t("timeline.immersive.standoutEmpty", {
            defaultValue: "再陪你几天，这里会出现更多值得回来的瞬间。",
          })}
        </p>
      ) : (
        <ul className="space-y-0">
          {items.map((item) => (
            <li key={item.episode_id}>
              <button
                type="button"
                onClick={() => onSelectEpisode(item.episode_id)}
                className="block w-full border-b border-dashed border-border/40 py-2.5 text-left text-[12.5px] leading-[1.45] text-foreground/85 last:border-b-0 hover:bg-foreground/5"
              >
                {item.source === "user" && (
                  <span className="mr-1 text-[#b87a78]">♡</span>
                )}
                {item.title || t("timeline.immersive.untitledMoment", { defaultValue: "未命名" })}
                <span className="mt-0.5 block text-[10px] text-muted-foreground">
                  {item.date}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
