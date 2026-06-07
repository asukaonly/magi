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
    case "chat_projector":
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

/**
 * Display label for a source_type. Pass `t` (from useTranslation) to get the
 * localized label; without it, falls back to the English text. Brand names
 * (Chrome, Git, Claude) are identical across locales and skip i18n.
 */
export function labelForSource(
  sourceType: string,
  t?: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const key = sourceType.toLowerCase().replace(/-/g, "_");
  const labels: Record<string, { i18nKey?: string; text: string }> = {
    manual_entry: { i18nKey: "timeline.source.manualEntry", text: "Your notes" },
    chrome_history: { text: "Chrome" },
    chrome: { text: "Chrome" },
    screen_time: { i18nKey: "timeline.source.screen", text: "Screen" },
    screen: { i18nKey: "timeline.source.screen", text: "Screen" },
    chat: { i18nKey: "timeline.source.chat", text: "Chat" },
    chat_message: { i18nKey: "timeline.source.chat", text: "Chat" },
    // chat_projector is the memory-layer source for projected chat turns —
    // surface it as plain "Chat", same as the chat sensor, not the raw id.
    chat_projector: { i18nKey: "timeline.source.chat", text: "Chat" },
    calendar: { i18nKey: "timeline.source.calendar", text: "Calendar" },
    calendar_plugin: { i18nKey: "timeline.source.calendar", text: "Calendar" },
    netease_music: { i18nKey: "timeline.source.music", text: "Music" },
    music: { i18nKey: "timeline.source.music", text: "Music" },
    system_media: { i18nKey: "timeline.source.music", text: "Music" },
    git_activity: { text: "Git" },
    git: { text: "Git" },
    terminal_history: { i18nKey: "timeline.source.terminal", text: "Terminal" },
    terminal: { i18nKey: "timeline.source.terminal", text: "Terminal" },
    photo_library: { i18nKey: "timeline.source.photo", text: "Photos" },
    photo: { i18nKey: "timeline.source.photo", text: "Photos" },
    apple_health: { i18nKey: "timeline.source.health", text: "Health" },
    health: { i18nKey: "timeline.source.health", text: "Health" },
    claude: { text: "Claude" },
    ai_assistant: { text: "AI" },
    memory: { i18nKey: "timeline.source.memory", text: "Memory" },
  };
  const entry = labels[key];
  if (!entry) return sourceType;
  return entry.i18nKey && t ? t(entry.i18nKey, { defaultValue: entry.text }) : entry.text;
}
