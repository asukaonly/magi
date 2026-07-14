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

const CUSTOM_ICON_IDS: Record<string, CustomIconKey> = {
  'brand:googlechrome': 'googlechrome',
  'custom:photo-library': 'photo-library',
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

const resolveCustomIcon = (iconId: string | null | undefined): CustomIconKey | null =>
  CUSTOM_ICON_IDS[normalizeIconKey(iconId)] ?? null;

const resolveBrandIcon = (iconId: string | null | undefined): SimpleIcon | null => {
  const normalized = normalizeIconKey(iconId);
  const { namespace, key } = stripIconNamespace(normalized);
  if (namespace === 'lucide' || normalized.startsWith('custom:')) return null;
  return BRAND_ICONS[key] ?? null;
};

const resolveLucideIcon = (iconId: string | null | undefined): LucideIcon => {
  const normalized = normalizeIconKey(iconId);
  const { namespace, key } = stripIconNamespace(normalized);
  if (namespace === 'brand' || normalized.startsWith('custom:')) return Activity;
  return LUCIDE_ICONS[key] ?? Activity;
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
  className,
}: PluginIconProps): JSX.Element {
  const baseClassName = cn('h-4 w-4', className);
  const customIcon = resolveCustomIcon(iconId);
  if (customIcon === 'googlechrome') {
    return <GoogleChromeIcon className={baseClassName} />;
  }
  if (customIcon === 'photo-library') {
    return <PhotoLibraryIcon className={baseClassName} />;
  }

  const brandIcon = resolveBrandIcon(iconId);
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

  const Icon = resolveLucideIcon(iconId);
  return <Icon data-testid="plugin-icon-fallback" className={baseClassName} aria-hidden="true" />;
}
