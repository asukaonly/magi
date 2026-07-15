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
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden bg-[#fbf4ea] dark:bg-[#171311]">
      {/* Decorative background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(251,244,234,0.98)_0%,rgba(255,249,241,0.95)_48%,rgba(244,236,226,0.94)_100%)] dark:bg-[linear-gradient(135deg,rgba(23,19,17,0.98)_0%,rgba(31,25,21,0.96)_48%,rgba(21,17,16,0.96)_100%)]" />
        <div className="absolute left-1/2 top-[46%] h-[34rem] w-[52rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#efd6bc]/48 blur-3xl dark:bg-[#704d36]/24" />
        <div className="absolute -bottom-24 -left-24 h-[24rem] w-[24rem] rounded-full bg-[#ecd28a]/24 blur-3xl dark:bg-[#74572f]/16" />
        <div className="absolute -right-24 top-24 h-[22rem] w-[22rem] rounded-full bg-[#c7d6bb]/24 blur-3xl dark:bg-[#4d5d4e]/18" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(255,250,243,0.42)_0%,rgba(255,250,243,0)_60%)] dark:bg-[radial-gradient(ellipse_at_center,rgba(255,245,235,0.05)_0%,rgba(255,245,235,0)_60%)]" />
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
          <div className="text-[2.4rem] font-semibold leading-none text-[#8b5737] dark:text-[#efb084] sm:text-[3.25rem]">
            {t('welcome.brand')}
          </div>
        </div>

        {/* Title */}
        <h1 className="text-[2.3rem] font-bold leading-tight tracking-normal text-[#3b2b22] dark:text-[#f2e7db] sm:text-[2.85rem]">
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
          transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
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
                'relative flex h-11 min-w-12 items-center justify-center px-2 text-xs font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b5737]/20',
                language === lang.value
                  ? 'text-[#6f422c] after:absolute after:bottom-1.5 after:left-2 after:right-2 after:h-px after:bg-[#8b5737]/55 dark:text-[#efb084] dark:after:bg-[#efb084]/55'
                  : 'text-[#9a8578] hover:text-[#3a2a22] dark:text-[#a8978c] dark:hover:text-[#f0e4d7]'
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
