import { BrainCircuit, Check, X } from 'lucide-react';
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
  const hasOverride = value !== 'auto';

  return (
    <div
      className={`flex h-8 items-center rounded-lg transition-colors ${hasOverride ? 'bg-muted/40 text-foreground' : ''}`}
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={t('chat.reasoning.controlLabel')}
            title={t('chat.reasoning.controlTitle', { mode: label })}
            className={`flex h-8 items-center justify-center gap-1.5 px-2 text-xs transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-45 ${hasOverride ? 'rounded-l-lg pr-1' : 'w-8 rounded-lg text-muted-foreground'}`}
          >
            <BrainCircuit className="h-4 w-4" />
            {hasOverride ? (
              <span>{t('chat.reasoning.turnOverride', { mode: label })}</span>
            ) : null}
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
      {hasOverride ? (
        <button
          type="button"
          onClick={() => onChange('auto')}
          disabled={disabled}
          aria-label={t('chat.reasoning.clearOverride')}
          title={t('chat.reasoning.clearOverride')}
          className="flex h-8 w-7 items-center justify-center rounded-r-lg text-muted-foreground transition-colors hover:bg-muted/55 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
};
