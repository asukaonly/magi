import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface ModeSelectionProps {
  value: 'quick' | 'expert' | null;
  onChange: (mode: 'quick' | 'expert') => void;
}

export const ModeSelection: React.FC<ModeSelectionProps> = ({ value, onChange }) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="grid w-full max-w-4xl gap-5 md:grid-cols-2">
      <div>
        <motion.div whileHover={shouldReduceMotion ? undefined : { y: -2 }} transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}>
          <Card
            onClick={() => onChange('quick')}
            onKeyDown={(e) => e.key === 'Enter' && onChange('quick')}
            tabIndex={0}
            role="button"
            aria-pressed={value === 'quick'}
            aria-label={t('mode.quick')}
            className={cn(
              'min-h-[140px] cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
              value === 'quick' ? 'border-primary shadow-sm' : 'hover:border-primary/40'
            )}
          >
            <CardHeader className="pb-2 pt-5">
              <CardTitle className="text-xl">{t('mode.quick')}</CardTitle>
            </CardHeader>
            <CardContent className="text-base text-muted-foreground">
              {t('mode.quickDesc')}
            </CardContent>
          </Card>
        </motion.div>
      </div>
      <div>
        <motion.div whileHover={shouldReduceMotion ? undefined : { y: -2 }} transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}>
          <Card
            onClick={() => onChange('expert')}
            onKeyDown={(e) => e.key === 'Enter' && onChange('expert')}
            tabIndex={0}
            role="button"
            aria-pressed={value === 'expert'}
            aria-label={t('mode.expert')}
            className={cn(
              'min-h-[140px] cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
              value === 'expert' ? 'border-primary shadow-sm' : 'hover:border-primary/40'
            )}
          >
            <CardHeader className="pb-2 pt-5">
              <CardTitle className="text-xl">{t('mode.expert')}</CardTitle>
            </CardHeader>
            <CardContent className="text-base text-muted-foreground">
              {t('mode.expertDesc')}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
};

export default ModeSelection;
