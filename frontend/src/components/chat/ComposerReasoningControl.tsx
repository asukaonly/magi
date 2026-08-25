import { Brain, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReasoningPreference } from '@/domain/chat/reasoning';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

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
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Brain className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={8}
        data-testid="composer-reasoning-menu"
        className="w-64 rounded-xl border-border/75 bg-card p-1.5 text-card-foreground shadow-[0_18px_48px_hsl(var(--foreground)/0.16)]"
      >
        {OPTIONS.map((option) => (
          <DropdownMenuItem
            key={option}
            onSelect={() => onChange(option)}
            className={`flex items-start gap-2.5 rounded-lg px-2.5 py-2.5 ${value === option ? 'bg-accent/70 text-accent-foreground' : ''}`}
          >
            <Check className={`mt-0.5 h-4 w-4 ${value === option ? 'opacity-100' : 'opacity-0'}`} />
            <span className="flex flex-col gap-0.5">
              <span>{t(`chat.reasoning.${option}.label`)}</span>
              <span className={`text-xs leading-5 ${value === option ? 'text-accent-foreground/70' : 'text-muted-foreground'}`}>
                {t(`chat.reasoning.${option}.description`)}
              </span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
