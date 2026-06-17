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

type CustomIconKey = 'googlechrome' | 'photo-library';

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

const CUSTOM_ICON_ALIASES: Record<string, CustomIconKey> = {
  chrome: 'googlechrome',
  chrome_history: 'googlechrome',
  chrome_history_core: 'googlechrome',
  'chrome-history': 'googlechrome',
  googlechrome: 'googlechrome',
  photo_library: 'photo-library',
  'photo-library': 'photo-library',
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

const resolveCustomIcon = (...candidates: Array<string | null | undefined>): CustomIconKey | null => {
  for (const candidate of candidates) {
    const normalized = normalizeIconKey(candidate);
    const { key } = stripIconNamespace(normalized);
    const aliasKey = key.replace(/-/g, '_');
    const iconKey = CUSTOM_ICON_ALIASES[key] || CUSTOM_ICON_ALIASES[aliasKey];
    if (iconKey) {
      return iconKey;
    }
  }
  return null;
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

function GoogleChromeIcon({ className }: { className: string }): JSX.Element {
  return (
    <svg
      data-testid="plugin-icon-googlechrome"
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" fill="#fff" />
      <path
        data-icon-color="red"
        fill="#EA4335"
        d="M12 2a10 10 0 0 1 8.66 5H12a5 5 0 0 0-4.33 2.5L5.17 5.17A9.96 9.96 0 0 1 12 2Z"
      />
      <path
        data-icon-color="yellow"
        fill="#FBBC04"
        d="M20.66 7A10 10 0 0 1 12 22l4.33-7.5A5 5 0 0 0 12 7h8.66Z"
      />
      <path
        data-icon-color="green"
        fill="#34A853"
        d="M12 22A10 10 0 0 1 5.17 5.17l4.33 7.5A5 5 0 0 0 16.33 14.5L12 22Z"
      />
      <circle cx="12" cy="12" r="5.15" fill="#fff" />
      <circle data-icon-color="blue" cx="12" cy="12" r="3.85" fill="#4285F4" />
    </svg>
  );
}

function PhotoLibraryIcon({ className }: { className: string }): JSX.Element {
  return (
    <svg
      data-testid="plugin-icon-photo-library"
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9.2" fill="#fff" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#EF4444" transform="rotate(0 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#F97316" transform="rotate(45 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#EAB308" transform="rotate(90 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#22C55E" transform="rotate(135 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#38BDF8" transform="rotate(180 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#6366F1" transform="rotate(225 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#A855F7" transform="rotate(270 12 12)" />
      <ellipse cx="12" cy="6.1" rx="2.05" ry="4.1" fill="#EC4899" transform="rotate(315 12 12)" />
      <circle cx="12" cy="12" r="2.25" fill="#fff" />
      <circle cx="12" cy="12" r="1.15" fill="hsl(var(--muted-foreground))" fillOpacity="0.55" />
    </svg>
  );
}

export function PluginIcon({
  iconId,
  pluginId,
  sourceName,
  className,
}: PluginIconProps): JSX.Element {
  const baseClassName = cn('h-4 w-4', className);
  const customIcon = resolveCustomIcon(iconId, pluginId, sourceName);
  if (customIcon === 'googlechrome') {
    return <GoogleChromeIcon className={baseClassName} />;
  }
  if (customIcon === 'photo-library') {
    return <PhotoLibraryIcon className={baseClassName} />;
  }

  const brandIcon = resolveBrandIcon(iconId, pluginId, sourceName);
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
