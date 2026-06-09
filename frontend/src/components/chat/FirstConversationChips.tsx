import { useTranslation } from 'react-i18next';

export interface FirstConversationChipsProps {
  /** Called with the chip's translated text when clicked. */
  onPick: (prompt: string) => void;
}

/**
 * Four hardcoded starter prompts shown above the chat composer in the user's
 * very first conversation. Two are "works immediately" (general LLM tasks);
 * two are "shows what magi knows about you" (will trigger Plan 4's suggestion
 * layer when data is missing; for Plan 3 they're sent through verbatim).
 */
const CHIPS = [
  'firstConversation.chips.refineText',
  'firstConversation.chips.plan',
  'firstConversation.chips.codeThisWeek',
  'firstConversation.chips.recallContact',
] as const;

export function FirstConversationChips({ onPick }: FirstConversationChipsProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  return (
    <div className="flex flex-wrap gap-2">
      {CHIPS.map((key) => {
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
