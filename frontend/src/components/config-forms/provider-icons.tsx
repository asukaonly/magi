import anthropicIcon from '@/assets/provider-icons/anthropic.svg?raw';
import chatglmIcon from '@/assets/provider-icons/chatglm-color.svg?raw';
import deepseekIcon from '@/assets/provider-icons/deepseek-color.svg?raw';
import geminiIcon from '@/assets/provider-icons/gemini-color.svg?raw';
import kimiIcon from '@/assets/provider-icons/kimi.svg?raw';
import minimaxIcon from '@/assets/provider-icons/minimax-color.svg?raw';
import openaiIcon from '@/assets/provider-icons/openai.svg?raw';
import { cn } from '@/lib/utils';

interface ProviderIconProps {
  providerId?: string;
  iconName?: string;
  className?: string;
}

const iconShellClassName =
  'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-background/90 shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

const customGlyphClassName = 'h-[18px] w-[18px]';

const CustomIcon = () => (
  <svg
    viewBox="0 0 24 24"
    className={customGlyphClassName}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 5v14" />
    <path d="M5 12h14" />
    <path d="m8 8 8 8" />
  </svg>
);

const ICON_SVGS: Record<string, string> = {
  openai: openaiIcon,
  anthropic: anthropicIcon,
  glm: chatglmIcon,
  gemini: geminiIcon,
  deepseek: deepseekIcon,
  kimi: kimiIcon,
  minimax: minimaxIcon,
};

function sanitizeSvgMarkup(svgMarkup: string): string {
  return svgMarkup.replace(/<title>.*?<\/title>/gis, '').trim();
}

export function ProviderIcon({ providerId, iconName, className }: ProviderIconProps): JSX.Element {
  const resolvedIconName = (iconName || providerId || 'custom').trim().toLowerCase();
  const svgMarkup = ICON_SVGS[resolvedIconName];
  const sanitizedSvgMarkup = svgMarkup ? sanitizeSvgMarkup(svgMarkup) : null;

  return (
    <span
      data-testid={`llm-provider-icon-${resolvedIconName}`}
      className={cn(iconShellClassName, 'text-foreground', className)}
      aria-hidden="true"
    >
      {sanitizedSvgMarkup ? (
        <span
          className="h-5 w-5 [&>svg]:block [&>svg]:h-full [&>svg]:w-full"
          dangerouslySetInnerHTML={{ __html: sanitizedSvgMarkup }}
        />
      ) : (
        <CustomIcon />
      )}
    </span>
  );
}
