import React from 'react';
import { useTranslation } from 'react-i18next';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import magiMark from '@/assets/magi-mark.png';
import { ONBOARDING_PRIMARY_ACTION_CLASS } from './onboardingStyles';

type LanguageCode = 'zh' | 'en';

interface WelcomeScreenProps {
  language: LanguageCode;
  onLanguageChange: (lang: LanguageCode) => void;
  onContinue: () => void;
}

const languages: { value: LanguageCode; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'EN' },
];

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
  language,
  onLanguageChange,
  onContinue,
}) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="absolute inset-0 z-50 flex flex-col items-center justify-center overflow-hidden bg-background">
      {/* Decorative background — 全部走主题 token,随主题切换变色 */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[linear-gradient(135deg,hsl(var(--background))_0%,hsl(var(--card))_48%,hsl(var(--muted))_100%)]" />
        <div className="absolute left-1/2 top-[46%] h-[34rem] w-[52rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/15 blur-3xl" />
        <div className="absolute -bottom-24 -left-24 h-[24rem] w-[24rem] rounded-full bg-accent blur-3xl" />
        <div className="absolute -right-24 top-24 h-[22rem] w-[22rem] rounded-full bg-muted blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,hsl(var(--card)/0.42)_0%,transparent_60%)]" />
      </div>

      {/* Center content */}
      <motion.div
        className="relative z-10 flex max-w-4xl flex-col items-center px-6 text-center"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: shouldReduceMotion ? 0 : 0.5, ease: 'easeOut' }}
      >
        {/* Logo / Brand */}
        <div className="mb-8 inline-flex items-center gap-4">
          <img
            src={magiMark}
            alt=""
            className="h-[4.5rem] w-[4.5rem] shrink-0"
            aria-hidden="true"
          />
          <div className="font-onboarding-display text-[2.4rem] font-semibold leading-none text-primary sm:text-[3.25rem]">
            {t('welcome.brand')}
          </div>
        </div>

        {/* Title */}
        <h1 className="font-onboarding-display text-[2.3rem] font-bold leading-tight tracking-normal text-foreground sm:text-[2.85rem]">
          {t('welcome.title')}
        </h1>

        {/* Get Started CTA */}
        <motion.button
          type="button"
          onClick={onContinue}
          className={cn(
            'group mt-10 inline-flex items-center justify-center gap-2.5',
            ONBOARDING_PRIMARY_ACTION_CLASS,
            'h-12 min-w-[9.5rem] px-6',
          )}
          whileHover={shouldReduceMotion ? undefined : { y: -1 }}
          whileTap={shouldReduceMotion ? undefined : { scale: 0.98 }}
          transition={{ duration: shouldReduceMotion ? 0 : 0.15, ease: 'easeOut' }}
        >
          {t('welcome.getStarted')}
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </motion.button>
      </motion.div>

      {/* Language toggle - bottom left */}
      <div className="absolute bottom-6 left-6 z-10">
        <div className="flex items-center gap-1">
          {languages.map((lang) => (
            <button
              key={lang.value}
              type="button"
              onClick={() => onLanguageChange(lang.value)}
              aria-pressed={language === lang.value}
              className={cn(
                'relative flex h-11 min-w-12 items-center justify-center px-2 text-xs font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20',
                language === lang.value
                  ? 'text-primary after:absolute after:bottom-1.5 after:left-2 after:right-2 after:h-px after:bg-primary/55'
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
