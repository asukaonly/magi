import React from "react";
import {
  Activity,
  Calendar,
  Feather,
  Gamepad2,
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
 * Render an icon for a semantic source type. Brand-recognizable sources
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
    case "chat_projector":
      return <MessageCircle className={cls} aria-hidden="true" />;
    case "calendar":
    case "calendar_plugin":
      return <Calendar className={cls} aria-hidden="true" />;
    case "netease_music":
    case "music":
    case "system_media":
      return <Music className={cls} aria-hidden="true" />;
    case "steam_play_history":
    case "game_records":
      return <Gamepad2 className={cls} aria-hidden="true" />;
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
    case "claude_code_agent_history":
    case "codex_agent_history":
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

export function labelForSource(
  sourceType: string,
  t?: (key: string, options?: Record<string, unknown>) => string,
): string {
  const key = sourceType.toLowerCase().replace(/-/g, "_");
  const labels: Record<string, { i18nKey?: string; fallback: string }> = {
    manual_entry: { i18nKey: "timeline.manualEntry.groupLabel", fallback: "你的记录" },
    chrome_history: { i18nKey: "timeline.sources.chrome_history", fallback: "Chrome" },
    chrome: { i18nKey: "timeline.sources.chrome_history", fallback: "Chrome" },
    screen_time: { i18nKey: "timeline.sources.screen_time", fallback: "屏幕" },
    screen: { i18nKey: "timeline.sources.screen_time", fallback: "屏幕" },
    chat: { i18nKey: "timeline.sources.chat", fallback: "聊天" },
    chat_message: { i18nKey: "timeline.sources.chat", fallback: "聊天" },
    // chat_projector is the memory-layer source for projected chat turns —
    // surface it as plain "聊天", same as the chat source, not the raw id.
    chat_projector: { i18nKey: "timeline.sources.chat", fallback: "聊天" },
    calendar: { i18nKey: "timeline.sources.calendar", fallback: "日历" },
    calendar_plugin: { i18nKey: "timeline.sources.calendar", fallback: "日历" },
    netease_music: { i18nKey: "timeline.sources.netease_music", fallback: "音乐" },
    music: { i18nKey: "timeline.sources.system_media", fallback: "音乐" },
    system_media: { i18nKey: "timeline.sources.system_media", fallback: "音乐" },
    steam_play_history: { i18nKey: "timeline.sources.steam_play_history", fallback: "Steam" },
    git_activity: { i18nKey: "timeline.sources.git_activity", fallback: "Git" },
    git: { i18nKey: "timeline.sources.git_activity", fallback: "Git" },
    terminal_history: { i18nKey: "timeline.sources.terminal_history", fallback: "终端" },
    terminal: { i18nKey: "timeline.sources.terminal_history", fallback: "终端" },
    photo_library: { i18nKey: "timeline.sources.photo_library", fallback: "相册" },
    photo: { i18nKey: "timeline.sources.photo_library", fallback: "相册" },
    apple_health: { i18nKey: "timeline.sources.apple_health", fallback: "健康" },
    health: { i18nKey: "timeline.sources.apple_health", fallback: "健康" },
    claude: { fallback: "Claude" },
    claude_code_agent_history: {
      i18nKey: "timeline.sources.claude_code_agent_history",
      fallback: "Claude Code",
    },
    codex_agent_history: {
      i18nKey: "timeline.sources.codex_agent_history",
      fallback: "Codex",
    },
    ai_assistant: { i18nKey: "timeline.sources.ai_assistant", fallback: "AI" },
    memory: { i18nKey: "timeline.sources.memory", fallback: "记忆" },
  };
  const label = labels[key];
  if (!label) return sourceType;
  return label.i18nKey && t ? t(label.i18nKey, { defaultValue: label.fallback }) : label.fallback;
}
