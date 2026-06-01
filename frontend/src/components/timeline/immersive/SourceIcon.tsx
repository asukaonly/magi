import React from "react";
import {
  Activity,
  Calendar,
  Feather,
  GitBranch,
  Heart,
  Image as ImageIcon,
  MessageCircle,
  Monitor,
  Music,
  Sparkles,
  Terminal,
} from "lucide-react";

import { cn } from "@/lib/utils";

interface SourceIconProps {
  sourceType: string;
  className?: string;
}

/**
 * Render an icon for a sensor source_type. Brand-recognizable sources
 * (Chrome) get a real SVG; everything else maps to a lucide icon. The
 * default fallback is the generic Activity glyph so unknown sources don't
 * crash the row.
 *
 * Mapping is case-insensitive on a normalized key (underscores and dashes
 * treated equivalently) so "chrome_history" and "chrome-history" both
 * resolve to the Chrome icon.
 */
export const SourceIcon: React.FC<SourceIconProps> = ({ sourceType, className }) => {
  const key = sourceType.toLowerCase().replace(/-/g, "_");
  const cls = cn("h-4 w-4 text-muted-foreground", className);

  // Brand-icon special cases (inline SVGs — keeping the bundle small,
  // no new dep). Add more here as we recognize new sources.
  if (key === "chrome_history" || key === "chrome") {
    return <ChromeBrandIcon className={cls} aria-hidden="true" />;
  }

  // Lucide mappings.
  switch (key) {
    case "manual_entry":
      return <Feather className={cls} aria-hidden="true" />;
    case "screen_time":
    case "screen":
      return <Monitor className={cls} aria-hidden="true" />;
    case "chat":
    case "chat_message":
    case "message":
      return <MessageCircle className={cls} aria-hidden="true" />;
    case "calendar":
    case "calendar_plugin":
      return <Calendar className={cls} aria-hidden="true" />;
    case "netease_music":
    case "music":
    case "system_media":
      return <Music className={cls} aria-hidden="true" />;
    case "git_activity":
    case "git":
      return <GitBranch className={cls} aria-hidden="true" />;
    case "terminal_history":
    case "terminal":
      return <Terminal className={cls} aria-hidden="true" />;
    case "photo_library":
    case "photo":
      return <ImageIcon className={cls} aria-hidden="true" />;
    case "apple_health":
    case "health":
      return <Heart className={cls} aria-hidden="true" />;
    case "claude":
    case "ai_assistant":
      return <Sparkles className={cls} aria-hidden="true" />;
    default:
      return <Activity className={cls} aria-hidden="true" />;
  }
};

/** Chrome's four-petal logo, simplified — no fill colors, just the shape. */
const ChromeBrandIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
  >
    <circle cx="12" cy="12" r="9.5" />
    <circle cx="12" cy="12" r="3.4" />
    <path d="M21.2 8.2H12" />
    <path d="M3.7 7.5l4.7 7.5" />
    <path d="M15.6 14.7l-4.5 7.6" />
  </svg>
);

/** zh-CN display label for a source_type. */
export function labelForSource(sourceType: string): string {
  const key = sourceType.toLowerCase().replace(/-/g, "_");
  const labels: Record<string, string> = {
    manual_entry: "你的记录",
    chrome_history: "Chrome",
    chrome: "Chrome",
    screen_time: "屏幕",
    screen: "屏幕",
    chat: "聊天",
    chat_message: "聊天",
    calendar: "日历",
    calendar_plugin: "日历",
    netease_music: "音乐",
    music: "音乐",
    system_media: "音乐",
    git_activity: "Git",
    git: "Git",
    terminal_history: "终端",
    terminal: "终端",
    photo_library: "相册",
    photo: "相册",
    apple_health: "健康",
    health: "健康",
    claude: "Claude",
    ai_assistant: "AI",
    memory: "记忆",
  };
  return labels[key] ?? sourceType;
}
