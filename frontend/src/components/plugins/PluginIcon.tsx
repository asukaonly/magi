import {
  Activity,
  BookOpen,
  Bot,
  CalendarDays,
  Code2,
  Database,
  FileText,
  Globe,
  HardDrive,
  Image,
  type LucideIcon,
  MessageCircle,
  Monitor,
  Music,
  Terminal,
} from 'lucide-react';
import type { SimpleIcon } from 'simple-icons';
import {
  siApple,
  siApplemusic,
  siFirefoxbrowser,
  siGit,
  siGithub,
  siGooglecalendar,
  siGooglechrome,
  siNeteasecloudmusic,
  siObsidian,
  siSafari,
  siSpotify,
  siSteam,
  siTelegram,
  siWechat,
} from 'simple-icons';
import { cn } from '@/lib/utils';

interface PluginIconProps {
  iconId?: string | null;
  pluginId?: string | null;
  sourceName?: string | null;
  className?: string;
}

const BRAND_ICONS: Record<string, SimpleIcon> = {
  apple: siApple,
  applemusic: siApplemusic,
  firefoxbrowser: siFirefoxbrowser,
  git: siGit,
  github: siGithub,
  googlecalendar: siGooglecalendar,
  googlechrome: siGooglechrome,
  neteasecloudmusic: siNeteasecloudmusic,
  obsidian: siObsidian,
  safari: siSafari,
  spotify: siSpotify,
  steam: siSteam,
  telegram: siTelegram,
  wechat: siWechat,
};

const BRAND_ALIASES: Record<string, string> = {
  chrome: 'googlechrome',
  chrome_history: 'googlechrome',
  chrome_history_core: 'googlechrome',
  'chrome-history': 'googlechrome',
  browser_history_core: 'googlechrome',
  firefox: 'firefoxbrowser',
  firefox_history: 'firefoxbrowser',
  'firefox-history': 'firefoxbrowser',
  safari_history: 'safari',
  'safari-history': 'safari',
  steam_play_history: 'steam',
  'steam-play-history': 'steam',
  netease_music: 'neteasecloudmusic',
  'netease-music': 'neteasecloudmusic',
  git_activity: 'git',
  'git-activity': 'git',
  obsidian_vault: 'obsidian',
  'obsidian-vault': 'obsidian',
  weixin: 'wechat',
  wechat: 'wechat',
  telegram: 'telegram',
  github: 'github',
  spotify: 'spotify',
  system_media: 'applemusic',
  'system-media': 'applemusic',
};

const LUCIDE_ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  book: BookOpen,
  bot: Bot,
  browser: Globe,
  calendar: CalendarDays,
  'calendar-days': CalendarDays,
  code: Code2,
  database: Database,
  file: FileText,
  'file-text': FileText,
  globe: Globe,
  harddrive: HardDrive,
  'hard-drive': HardDrive,
  image: Image,
  monitor: Monitor,
  music: Music,
  terminal: Terminal,
  chat: MessageCircle,
  message: MessageCircle,
  'message-circle': MessageCircle,
};

const LUCIDE_ALIASES: Record<string, string> = {
  calendar_plugin: 'calendar-days',
  coding_agent_history: 'code',
  local_documents: 'file-text',
  'local-documents': 'file-text',
  photo_library: 'image',
  'photo-library': 'image',
  screen: 'monitor',
  screen_time: 'monitor',
  'screen-time': 'monitor',
  screenshot_timeline: 'monitor',
  terminal_history: 'terminal',
  'terminal-history': 'terminal',
  chat_projector: 'message-circle',
};

const normalizeIconKey = (value: string | null | undefined): string => (
  String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^simple:/, 'brand:')
);

const stripIconNamespace = (value: string): { namespace: 'brand' | 'lucide' | null; key: string } => {
  if (value.startsWith('brand:')) {
    return { namespace: 'brand', key: value.slice('brand:'.length) };
  }
  if (value.startsWith('lucide:')) {
    return { namespace: 'lucide', key: value.slice('lucide:'.length) };
  }
  return { namespace: null, key: value };
};

const resolveBrandIcon = (...candidates: Array<string | null | undefined>): SimpleIcon | null => {
  for (const candidate of candidates) {
    const normalized = normalizeIconKey(candidate);
    const { namespace, key } = stripIconNamespace(normalized);
    const aliasKey = key.replace(/-/g, '_');
    const slug = BRAND_ALIASES[key] || BRAND_ALIASES[aliasKey] || key;
    if (namespace === 'lucide') {
      continue;
    }
    if (BRAND_ICONS[slug]) {
      return BRAND_ICONS[slug];
    }
  }
  return null;
};

const resolveLucideIcon = (...candidates: Array<string | null | undefined>): LucideIcon => {
  for (const candidate of candidates) {
    const normalized = normalizeIconKey(candidate);
    const { namespace, key } = stripIconNamespace(normalized);
    if (namespace === 'brand') {
      continue;
    }
    const aliasKey = key.replace(/-/g, '_');
    const iconKey = LUCIDE_ALIASES[key] || LUCIDE_ALIASES[aliasKey] || key;
    if (LUCIDE_ICONS[iconKey]) {
      return LUCIDE_ICONS[iconKey];
    }
  }
  return Activity;
};

export function PluginIcon({
  iconId,
  pluginId,
  sourceName,
  className,
}: PluginIconProps): JSX.Element {
  const brandIcon = resolveBrandIcon(iconId, pluginId, sourceName);
  const baseClassName = cn('h-4 w-4', className);
  if (brandIcon) {
    return (
      <svg
        data-testid={`plugin-icon-${brandIcon.slug}`}
        viewBox="0 0 24 24"
        fill={`#${brandIcon.hex}`}
        className={baseClassName}
        aria-hidden="true"
      >
        <path d={brandIcon.path} />
      </svg>
    );
  }

  const Icon = resolveLucideIcon(iconId, pluginId, sourceName);
  return <Icon data-testid="plugin-icon-fallback" className={baseClassName} aria-hidden="true" />;
}
