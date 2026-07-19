import {
  Activity,
  BookOpen,
  Bot,
  CalendarDays,
  ChartNoAxesColumn,
  Code2,
  Database,
  FileText,
  Gamepad2,
  Globe,
  HardDrive,
  Image,
  Images,
  type LucideIcon,
  MessageCircle,
  Monitor,
  Music,
  Scan,
  Terminal,
} from 'lucide-react';
import type { SimpleIcon } from 'simple-icons';
import {
  siApple,
  siApplemusic,
  siClaudecode,
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

type CustomIconKey = 'apple-photos' | 'codex' | 'googlechrome' | 'microsoft-edge';

const BRAND_ICONS: Record<string, SimpleIcon> = {
  apple: siApple,
  applemusic: siApplemusic,
  claudecode: siClaudecode,
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
  'chart-no-axes-column': ChartNoAxesColumn,
  code: Code2,
  database: Database,
  file: FileText,
  'file-text': FileText,
  globe: Globe,
  'gamepad-2': Gamepad2,
  harddrive: HardDrive,
  'hard-drive': HardDrive,
  image: Image,
  images: Images,
  monitor: Monitor,
  music: Music,
  scan: Scan,
  terminal: Terminal,
  chat: MessageCircle,
  message: MessageCircle,
  'message-circle': MessageCircle,
};

const CUSTOM_ICON_IDS: Record<string, CustomIconKey> = {
  'brand:googlechrome': 'googlechrome',
  'custom:apple-photos': 'apple-photos',
  'custom:codex': 'codex',
  'custom:microsoft-edge': 'microsoft-edge',
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

function ApplePhotosIcon({ className }: { className: string }): JSX.Element {
  return (
    <svg
      data-testid="plugin-icon-apple-photos"
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

function CodexIcon({ className }: { className: string }): JSX.Element {
  return (
    <svg
      data-testid="plugin-icon-codex"
      viewBox="0 0 24 24"
      fill="currentColor"
      fillRule="evenodd"
      className={className}
      aria-hidden="true"
    >
      <path d="M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 0 0-.856 0l-5.97 3.473Zm10.609 8.8V12.06c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 0 1 .476 0l4.543 2.617c1.309.76 2.189 2.378 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163ZM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898ZM12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128Zm1.796 7.23c-1 0-1.927-.332-2.712-.927l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974 4.472-4.614 4.472Zm-5.637-5.303-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 0 1 4.21 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 0 1-.476 0Zm-.262 3.9c-2.688 0-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523Zm5.899 2.83a5.947 5.947 0 0 0 5.827-4.756C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0 0 10.205 0a5.947 5.947 0 0 0-5.827 4.757C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 0 0 4.162 1.713Z" />
    </svg>
  );
}

function MicrosoftEdgeIcon({ className }: { className: string }): JSX.Element {
  return (
    <svg
      data-testid="plugin-icon-microsoft-edge"
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
    >
      <path fill="#0C59A4" d="M21.4 15.3A9.8 9.8 0 0 0 3.3 7.8c1.8-2 4.6-3.2 7.7-2.8 3.4.4 5.8 2.6 6.5 5.3H8.1c.5-1.6 2-2.7 3.8-2.7 1.2 0 2.3.5 3 1.3h2.4C16.2 6.6 14 5.2 11.4 5.2c-4.2 0-7.6 3.3-7.6 7.4 0 .3 0 .6.1.9.8-1.2 2-2.1 3.4-2.7a6 6 0 0 0 5.4 8.6c3.7 0 6.8-2 8.1-5Z" />
      <path fill="#0AA7B5" d="M3.8 12.6c0-4.1 3.4-7.4 7.6-7.4 2.6 0 4.8 1.4 5.9 3.7h-2.4a4 4 0 0 0-3-1.3c-2.2 0-4 1.7-4 3.9 0 2.8 2.4 5 5.6 5 2 0 3.8-.6 5.1-1.7-.8 3.3-3.8 5.8-7.4 5.8a7.5 7.5 0 0 1-7.4-8Z" />
      <path fill="#16C79A" d="M8.1 10.3h9.4c-.7-2.7-3.1-4.9-6.5-5.3-3.1-.4-5.9.8-7.7 2.8A9.8 9.8 0 0 1 21.4 15.3c-1.5.8-3.3 1.2-5.2 1.2-3.3 0-6.2-1.4-7.5-3.6a3.8 3.8 0 0 1-.6-2.6Z" />
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
  if (customIcon === 'apple-photos') {
    return <ApplePhotosIcon className={baseClassName} />;
  }
  if (customIcon === 'codex') {
    return <CodexIcon className={baseClassName} />;
  }
  if (customIcon === 'microsoft-edge') {
    return <MicrosoftEdgeIcon className={baseClassName} />;
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
