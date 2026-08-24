import { BrainCircuit, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export type ReasoningPreference = 'auto' | 'fast' | 'deep';

type ComposerReasoningControlProps = {
  value: ReasoningPreference;
  onChange: (value: ReasoningPreference) => void;
  disabled?: boolean;
};

const OPTIONS: ReasoningPreference[] = ['auto', 'fast', 'deep'];

export const ComposerReasoningControl = ({
  value,
  onChange,
  disabled = false,
}: ComposerReasoningControlProps) => {
  const { t } = useTranslation();
  const label = t(`chat.reasoning.${value}.label`);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={t('chat.reasoning.controlLabel')}
          title={t('chat.reasoning.controlTitle', { mode: label })}
          className={`flex h-8 items-center justify-center gap-1.5 rounded-lg px-2 text-xs transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-45 ${value === 'auto' ? 'w-8 text-muted-foreground' : 'text-foreground'}`}
        >
          <BrainCircuit className="h-4 w-4" />
          {value === 'auto' ? null : <span>{label}</span>}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        {OPTIONS.map((option) => (
          <DropdownMenuItem
            key={option}
            onSelect={() => onChange(option)}
            className="flex items-start gap-2 rounded-lg py-2"
          >
            <Check className={`mt-0.5 h-4 w-4 ${value === option ? 'opacity-100' : 'opacity-0'}`} />
            <span className="flex flex-col gap-0.5">
              <span>{t(`chat.reasoning.${option}.label`)}</span>
              <span className="text-xs text-muted-foreground">
                {t(`chat.reasoning.${option}.description`)}
              </span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
