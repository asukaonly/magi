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
    <div className="flex flex-wrap gap-2">
      {CHIP_KEYS.map((key) => {
        const label = t(key);
        return (
          <button
            type="button"
            key={key}
            onClick={() => onPick(label)}
            className="rounded-full border border-[#d8c9b8] bg-white px-4 py-1.5 text-sm text-[#35261f] transition hover:bg-[#f4eadf] dark:border-[#7d685a] dark:bg-transparent dark:text-[#f4eadf]"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
