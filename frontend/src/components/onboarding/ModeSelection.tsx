import React from 'react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface ModeSelectionProps {
  value: 'quick' | 'expert' | null;
  onChange: (mode: 'quick' | 'expert') => void;
}

export const ModeSelection: React.FC<ModeSelectionProps> = ({ value, onChange }) => {
  const { t } = useTranslation('onboarding');

  return (
    <div className="grid w-full max-w-4xl gap-5 md:grid-cols-2">
      <div>
        <motion.div whileHover={{ y: -2 }} transition={{ duration: 0.15 }}>
          <Card
            onClick={() => onChange('quick')}
            className={cn(
              'min-h-[140px] cursor-pointer transition-colors',
              value === 'quick' ? 'border-violet-600 shadow-sm' : 'hover:border-violet-400/40'
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
        <motion.div whileHover={{ y: -2 }} transition={{ duration: 0.15 }}>
          <Card
            onClick={() => onChange('expert')}
            className={cn(
              'min-h-[140px] cursor-pointer transition-colors',
              value === 'expert' ? 'border-violet-600 shadow-sm' : 'hover:border-violet-400/40'
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
