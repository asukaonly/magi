import React from "react";
import {
  Activity,
  Calendar,
  Feather,
  Gamepad2,
  GitBranch,
  Globe,
  Heart,
  Image as ImageIcon,
  MessageCircle,
  Monitor,
  Music,
  Sparkles,
  Terminal,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { useSourceIcon } from './SourceIconProvider';

interface SourceIconProps {
  sourceType: string;
  className?: string;
}

/** Prefer installed plugin artwork, then a semantic source icon. */
export const SourceIcon: React.FC<SourceIconProps> = ({ sourceType, className }) => {
  const key = sourceType.toLowerCase().replace(/-/g, "_");
  const cls = cn("h-4 w-4 text-muted-foreground", className);
  const artwork = useSourceIcon(sourceType);
  if (artwork) return <PluginIcon iconId={artwork} className={cls} />;

  // Lucide mappings.
  switch (key) {
    case "chrome_history":
    case "chrome":
      return <Globe className={cls} aria-hidden="true" />;
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
  if (!label) return t ? t("timeline.review.unknownSource") : "Activity";
  return label.i18nKey && t ? t(label.i18nKey, { defaultValue: label.fallback }) : label.fallback;
}
