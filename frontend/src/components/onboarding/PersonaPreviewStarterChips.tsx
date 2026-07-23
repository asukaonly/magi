import { useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { ChevronDown, MessageCircleQuestion } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

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
  const shouldReduceMotion = useReducedMotion() ?? false;
  const [open, setOpen] = useState(true);

  return (
    <div>
      <button
        type="button"
        data-testid="persona-starter-prompts-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="group flex items-center gap-1.5 rounded-md px-1 py-1 text-xs text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 motion-reduce:transition-none"
      >
        <span>{t('personaPreview.starterPromptsLabel')}</span>
        <ChevronDown
          aria-hidden
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground/60 transition-transform duration-200 group-hover:text-muted-foreground',
            !open && '-rotate-90',
          )}
        />
      </button>
      {open ? (
        <motion.div
          initial={shouldReduceMotion ? false : { opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: shouldReduceMotion ? 0 : 0.18, ease: [0.22, 1, 0.36, 1] }}
          data-testid="persona-preview-starter-prompts"
          className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2"
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
        </motion.div>
      ) : null}
    </div>
  );
}
