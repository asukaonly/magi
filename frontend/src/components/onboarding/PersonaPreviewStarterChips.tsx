import { MessageCircleQuestion } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export interface PersonaPreviewStarterChipsProps {
  onPick: (prompt: string) => void;
}

const CHIP_KEYS = [
  'personaPreview.chip1',
  'personaPreview.chip2',
  'personaPreview.chip3',
  'personaPreview.chip4',
] as const;

export function PersonaPreviewStarterChips({
  onPick,
}: PersonaPreviewStarterChipsProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  return (
    <div
      data-testid="persona-preview-starter-prompts"
      className="grid grid-cols-1 gap-2 sm:grid-cols-2"
    >
      {CHIP_KEYS.map((key) => {
        const label = t(key);
        return (
          <button
            type="button"
            key={key}
            onClick={() => onPick(label)}
            className="group flex min-w-0 items-center gap-2.5 rounded-lg border border-border/60 bg-card px-3 py-2.5 text-left text-[13px] leading-5 text-muted-foreground shadow-[0_1px_2px_hsl(var(--foreground)/0.04)] transition-[border-color,color,box-shadow] duration-200 hover:border-primary/35 hover:text-foreground hover:shadow-[0_4px_14px_-10px_hsl(var(--foreground)/0.22)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 motion-reduce:transition-none"
          >
            <MessageCircleQuestion
              aria-hidden
              className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors duration-200 group-hover:text-primary"
            />
            <span className="min-w-0">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
