import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface ModeSelectionProps {
  value: 'quick' | 'expert' | null;
  onChange: (mode: 'quick' | 'expert') => void;
}

export const ModeSelection: React.FC<ModeSelectionProps> = ({ value, onChange }) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('mode.label')}</h3>
        <p className="mb-4 text-sm text-muted-foreground">{t('mode.description')}</p>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <motion.div whileHover={shouldReduceMotion ? undefined : { y: -2 }} transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}>
          <button
            onClick={() => onChange('quick')}
            onKeyDown={(e) => e.key === 'Enter' && onChange('quick')}
            role="button"
            aria-pressed={value === 'quick'}
            aria-label={t('mode.quick')}
            type="button"
            className={cn(
              'flex min-h-[132px] w-full flex-col rounded-lg border bg-background p-5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
              value === 'quick' ? 'border-primary bg-primary/5 shadow-sm' : 'border-border hover:border-primary/40'
            )}
          >
            <div className="space-y-2">
              <div className="text-2xl font-semibold">{t('mode.quick')}</div>
              <p className="text-base leading-7 text-muted-foreground">{t('mode.quickDesc')}</p>
            </div>
          </button>
        </motion.div>

        <motion.div whileHover={shouldReduceMotion ? undefined : { y: -2 }} transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}>
          <button
            onClick={() => onChange('expert')}
            onKeyDown={(e) => e.key === 'Enter' && onChange('expert')}
            role="button"
            aria-pressed={value === 'expert'}
            aria-label={t('mode.expert')}
            type="button"
            className={cn(
              'flex min-h-[132px] w-full flex-col rounded-lg border bg-background p-5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
              value === 'expert' ? 'border-primary bg-primary/5 shadow-sm' : 'border-border hover:border-primary/40'
            )}
          >
            <div className="space-y-2">
              <div className="text-2xl font-semibold">{t('mode.expert')}</div>
              <p className="text-base leading-7 text-muted-foreground">{t('mode.expertDesc')}</p>
            </div>
          </button>
        </motion.div>
      </div>
    </div>
  );
};

export default ModeSelection;
