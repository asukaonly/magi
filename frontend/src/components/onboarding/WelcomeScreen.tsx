import React from 'react';
import { useTranslation } from 'react-i18next';
import { Rocket, Settings } from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

type LanguageCode = 'zh' | 'en';

interface WelcomeScreenProps {
  language: LanguageCode;
  onLanguageChange: (lang: LanguageCode) => void;
  onSelectMode: (mode: 'quick' | 'expert') => void;
}

const languages: { value: LanguageCode; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'EN' },
];

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
  language,
  onLanguageChange,
  onSelectMode,
}) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="relative flex min-h-screen w-full flex-col items-center justify-center overflow-hidden bg-gradient-to-br from-orange-50/80 via-background to-amber-50/60">
      {/* Decorative background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-40 -top-40 h-[500px] w-[500px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -bottom-32 -left-32 h-[400px] w-[400px] rounded-full bg-amber-200/20 blur-3xl" />
      </div>

      {/* Center content */}
      <motion.div
        className="relative z-10 flex flex-col items-center px-6 text-center"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: shouldReduceMotion ? 0 : 0.5, ease: 'easeOut' }}
      >
        {/* Logo / Brand */}
        <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <span className="text-2xl font-bold">M</span>
        </div>

        {/* Title */}
        <h1 className="mb-2 text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
          {t('welcome.title')}
        </h1>

        {/* Subtitle */}
        <p className="mb-12 text-lg text-muted-foreground sm:text-xl">
          {t('welcome.subtitle')}
        </p>

        {/* Mode cards */}
        <div className="grid w-full max-w-2xl gap-4 sm:grid-cols-2">
          <motion.button
            type="button"
            onClick={() => onSelectMode('quick')}
            className={cn(
              'group flex flex-col items-start gap-3 rounded-2xl border border-border/60 bg-white/70 p-6 text-left backdrop-blur-sm transition',
              'hover:border-primary/50 hover:bg-white/90 hover:shadow-lg hover:shadow-primary/5',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50'
            )}
            whileHover={shouldReduceMotion ? undefined : { y: -4 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary transition group-hover:bg-primary/15">
              <Rocket className="h-5 w-5" />
            </div>
            <div>
              <div className="text-lg font-semibold text-foreground">{t('welcome.quickMode')}</div>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {t('welcome.quickModeDesc')}
              </p>
            </div>
          </motion.button>

          <motion.button
            type="button"
            onClick={() => onSelectMode('expert')}
            className={cn(
              'group flex flex-col items-start gap-3 rounded-2xl border border-border/60 bg-white/70 p-6 text-left backdrop-blur-sm transition',
              'hover:border-primary/50 hover:bg-white/90 hover:shadow-lg hover:shadow-primary/5',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50'
            )}
            whileHover={shouldReduceMotion ? undefined : { y: -4 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary transition group-hover:bg-primary/15">
              <Settings className="h-5 w-5" />
            </div>
            <div>
              <div className="text-lg font-semibold text-foreground">{t('welcome.expertMode')}</div>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {t('welcome.expertModeDesc')}
              </p>
            </div>
          </motion.button>
        </div>
      </motion.div>

      {/* Language toggle - bottom left */}
      <div className="absolute bottom-6 left-6 z-10">
        <div className="flex items-center gap-1 rounded-full border border-border/50 bg-white/60 p-1 backdrop-blur-sm">
          {languages.map((lang) => (
            <button
              key={lang.value}
              type="button"
              onClick={() => onLanguageChange(lang.value)}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition',
                language === lang.value
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {lang.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default WelcomeScreen;
