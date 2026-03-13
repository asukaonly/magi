import { cn } from '@/lib/utils';

interface ProviderIconProps {
  providerId?: string;
  iconName?: string;
  className?: string;
}

type IconRenderer = () => JSX.Element;

const iconShellClassName =
  'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-background/90 shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

const glyphClassName = 'h-[18px] w-[18px]';

const OpenAIIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8.8 4.6a4.2 4.2 0 0 1 6.4 1.9l.2.7" />
    <path d="M18.1 8.1a4.2 4.2 0 0 1-1.3 6.6l-.6.4" />
    <path d="M15.2 19.4a4.2 4.2 0 0 1-6.4-1.9l-.2-.7" />
    <path d="M5.9 15.9a4.2 4.2 0 0 1 1.3-6.6l.6-.4" />
    <path d="M8.1 8.2 12 6l3.9 2.2v7.6L12 18l-3.9-2.2z" />
  </svg>
);

const AnthropicIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 18 12 6l5 12" />
    <path d="M9 13h6" />
  </svg>
);

const GLMIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 7.5A7 7 0 1 0 18 16" />
    <path d="M18 12h-5" />
    <path d="M18 12v4" />
  </svg>
);

const GeminiIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z" />
  </svg>
);

const DeepSeekIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 6.5h4.8a5.5 5.5 0 1 1 0 11H7z" />
    <path d="M10 11.2c1.2 0 2.3.4 3.2 1.2" />
    <path d="M7 17.5c2.4 0 4.8-1.1 6.2-2.8" />
  </svg>
);

const KimiIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 5v14" />
    <path d="m16 6-6 6 6 6" />
  </svg>
);

const MiniMaxIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4.5 18V6l3.5 4 4-4 4 4 3.5-4v12" />
  </svg>
);

const CustomIcon: IconRenderer = () => (
  <svg viewBox="0 0 24 24" className={glyphClassName} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14" />
    <path d="M5 12h14" />
    <path d="m8 8 8 8" />
  </svg>
);

const ICONS: Record<string, IconRenderer> = {
  openai: OpenAIIcon,
  anthropic: AnthropicIcon,
  glm: GLMIcon,
  gemini: GeminiIcon,
  deepseek: DeepSeekIcon,
  kimi: KimiIcon,
  minimax: MiniMaxIcon,
  custom: CustomIcon,
};

const TONES: Record<string, string> = {
  openai: 'text-slate-700',
  anthropic: 'text-amber-700',
  glm: 'text-emerald-700',
  gemini: 'text-blue-700',
  deepseek: 'text-cyan-700',
  kimi: 'text-fuchsia-700',
  minimax: 'text-rose-700',
  custom: 'text-zinc-700',
};

export function ProviderIcon({ providerId, iconName, className }: ProviderIconProps): JSX.Element {
  const resolvedIconName = (iconName || providerId || 'custom').trim().toLowerCase();
  const Icon = ICONS[resolvedIconName] || CustomIcon;

  return (
    <span
      data-testid={`llm-provider-icon-${resolvedIconName}`}
      className={cn(iconShellClassName, TONES[resolvedIconName] || TONES.custom, className)}
      aria-hidden="true"
    >
      <Icon />
    </span>
  );
}
