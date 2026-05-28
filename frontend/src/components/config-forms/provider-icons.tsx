import anthropicIcon from '@/assets/provider-icons/anthropic.svg?raw';
import bailianIcon from '@/assets/provider-icons/bailian-color.svg?raw';
import deepseekIcon from '@/assets/provider-icons/deepseek-color.svg?raw';
import geminiIcon from '@/assets/provider-icons/gemini-color.svg?raw';
import grokIcon from '@/assets/provider-icons/grok.svg?raw';
import kimiIcon from '@/assets/provider-icons/kimi.svg?raw';
import minimaxIcon from '@/assets/provider-icons/minimax-color.svg?raw';
import openaiIcon from '@/assets/provider-icons/openai.svg?raw';
import xiaomimimoIcon from '@/assets/provider-icons/xiaomimimo.svg?raw';
import zaiIcon from '@/assets/provider-icons/zai.svg?raw';
import { cn } from '@/lib/utils';

interface ProviderIconProps {
  providerId?: string;
  iconName?: string;
  displayName?: string;
  className?: string;
}

const iconShellClassName =
  'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-background/90 shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

const customGlyphClassName =
  'flex h-[18px] w-[18px] items-center justify-center text-[13px] font-semibold uppercase leading-none';

function getCustomProviderGlyph(displayName?: string, providerId?: string): string {
  const source = (displayName || providerId || 'C').trim();
  const firstCharacter = [...source][0] || 'C';
  return firstCharacter.toUpperCase();
}

const CustomIcon = ({ glyph }: { glyph: string }) => <span className={customGlyphClassName}>{glyph}</span>;

const ICON_SVGS: Record<string, string> = {
  openai: openaiIcon,
  anthropic: anthropicIcon,
  glm: zaiIcon,
  glm_codeplan: zaiIcon,
  zai: zaiIcon,
  gemini: geminiIcon,
  grok: grokIcon,
  deepseek: deepseekIcon,
  dashscope: bailianIcon,
  bailian: bailianIcon,
  kimi: kimiIcon,
  minimax: minimaxIcon,
  xiaomimimo: xiaomimimoIcon,
};

function sanitizeSvgMarkup(svgMarkup: string): string {
  return svgMarkup.replace(/<title>.*?<\/title>/gis, '').trim();
}

export function ProviderIcon({ providerId, iconName, displayName, className }: ProviderIconProps): JSX.Element {
  const resolvedIconName = (iconName || providerId || 'custom').trim().toLowerCase();
  const svgMarkup = ICON_SVGS[resolvedIconName];
  const sanitizedSvgMarkup = svgMarkup ? sanitizeSvgMarkup(svgMarkup) : null;
  const customGlyph = getCustomProviderGlyph(displayName, providerId);

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
        <CustomIcon glyph={customGlyph} />
      )}
    </span>
  );
}
