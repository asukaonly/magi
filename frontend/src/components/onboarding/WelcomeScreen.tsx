import React from 'react';
import { useTranslation } from 'react-i18next';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import magiMark from '@/assets/magi-mark.png';

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
        <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(251,244,234,0.98)_0%,rgba(255,249,241,0.94)_48%,rgba(244,236,226,0.92)_100%)] dark:bg-[linear-gradient(135deg,rgba(23,19,17,0.98)_0%,rgba(31,25,21,0.96)_48%,rgba(21,17,16,0.96)_100%)]" />
        <div className="absolute left-1/2 top-[-10rem] h-[30rem] w-[44rem] -translate-x-1/2 rounded-full bg-[#f2dcc3]/50 blur-3xl dark:bg-[#6b4c37]/25" />
        <div className="absolute -bottom-24 -left-24 h-[24rem] w-[24rem] rounded-full bg-[#ecd28a]/28 blur-3xl dark:bg-[#74572f]/18" />
        <div className="absolute -right-24 top-24 h-[22rem] w-[22rem] rounded-full bg-[#c7d6bb]/28 blur-3xl dark:bg-[#4d5d4e]/20" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.34)_0%,rgba(255,255,255,0)_64%)] dark:bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.05)_0%,rgba(255,255,255,0)_64%)]" />
      </div>

      {/* Center content */}
      <motion.div
        className="relative z-10 flex max-w-4xl flex-col items-center px-6 text-center"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: shouldReduceMotion ? 0 : 0.5, ease: 'easeOut' }}
      >
        {/* Logo / Brand */}
        <div className="mb-8 inline-flex items-center gap-3">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-[#ead9c8]/80 bg-[#fff7ef]/82 shadow-[0_16px_34px_-26px_rgba(120,80,44,0.42)] backdrop-blur-sm dark:border-[#584438]/70 dark:bg-[#241c18]/82 dark:shadow-[0_18px_36px_-28px_rgba(0,0,0,0.62)]">
            <img src={magiMark} alt="" className="h-10 w-10" aria-hidden="true" />
          </div>
          <div className="text-[1.7rem] font-semibold leading-none text-[#8b5737] dark:text-[#efb084] sm:text-3xl">
            {t('welcome.brand')}
          </div>
        </div>

        {/* Title */}
        <h1 className="mb-3 text-4xl font-bold tracking-normal text-[#3b2b22] dark:text-[#f2e7db] sm:text-5xl">
          {t('welcome.title')}
        </h1>

        {/* Subtitle */}
        <p className="mb-4 max-w-[32rem] text-base leading-7 text-[#7b6557] dark:text-[#c8b8aa] sm:text-lg sm:leading-8">
          <span className="block">{t('welcome.subtitleLine1')}</span>
          <span className="block">{t('welcome.subtitleLine2')}</span>
        </p>

        {/* Get Started CTA */}
        <motion.button
          type="button"
          onClick={onContinue}
          className="group mt-11 inline-flex h-12 items-center justify-center gap-2 rounded-[14px] border border-[#8f5532]/30 bg-[#a0623a] px-6 text-base font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.24),0_18px_36px_-24px_rgba(112,63,31,0.9)] transition hover:bg-[#965833] hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.28),0_20px_40px_-24px_rgba(112,63,31,0.95)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a0623a]/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[#fbf4ea] dark:border-[#efb084]/25 dark:bg-[#efb084] dark:text-[#2a1f1a] dark:hover:bg-[#f4bd94] dark:focus-visible:ring-[#efb084]/40 dark:focus-visible:ring-offset-[#171311]"
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
        <div className="flex items-center gap-1 rounded-full border border-[#e8dacd]/80 bg-[#fff8f1]/78 p-1 shadow-[0_16px_36px_-28px_rgba(92,62,41,0.38)] backdrop-blur-sm dark:border-[#5a4539]/80 dark:bg-[#241c18]/78 dark:shadow-[0_16px_40px_-28px_rgba(0,0,0,0.62)]">
          {languages.map((lang) => (
            <button
              key={lang.value}
              type="button"
              onClick={() => onLanguageChange(lang.value)}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition',
                language === lang.value
                  ? 'bg-[#f2dfcd] text-[#a0623a] dark:bg-[#3a2b24] dark:text-[#efb084]'
                  : 'text-[#8b7466] hover:text-[#3a2a22] dark:text-[#bba99c] dark:hover:text-[#f0e4d7]'
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
