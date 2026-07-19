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
      className="grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2"
    >
      {CHIP_KEYS.map((key) => {
        const label = t(key);
        return (
          <button
            type="button"
            key={key}
            onClick={() => onPick(label)}
            className="group flex min-w-0 items-start gap-2.5 rounded-md px-2 py-2 text-left text-[13px] leading-5 text-muted-foreground transition-[background-color,color] duration-200 hover:bg-muted/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15"
          >
            <span
              aria-hidden
              className="mt-2.5 h-px w-3 shrink-0 origin-left scale-x-75 bg-border transition-[background-color,transform] duration-200 group-hover:scale-x-100 group-hover:bg-primary/55"
            />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
