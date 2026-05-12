import React from 'react';
import { useTranslation } from 'react-i18next';
import { Rocket, Settings } from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';
import magiMark from '@/assets/magi-mark.png';

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

const modeCardBaseClass =
  'group relative flex flex-col items-start gap-3 overflow-hidden rounded-[28px] border p-6 text-left transition duration-200 backdrop-blur-sm focus-visible:outline-none focus-visible:ring-2';

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
  language,
  onLanguageChange,
  onSelectMode,
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
        className="relative z-10 flex flex-col items-center px-6 text-center"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: shouldReduceMotion ? 0 : 0.5, ease: 'easeOut' }}
      >
        {/* Logo / Brand */}
        <div className="mb-4 rounded-[1.75rem] border border-[#ead9c8]/80 bg-[#fff7ef]/80 p-3 shadow-[0_18px_40px_-28px_rgba(120,80,44,0.35)] backdrop-blur-sm dark:border-[#584438]/70 dark:bg-[#241c18]/80 dark:shadow-[0_20px_42px_-30px_rgba(0,0,0,0.6)]">
          <img src={magiMark} alt="Magi" className="h-16 w-16" />
        </div>

        {/* Title */}
        <h1 className="mb-2 text-4xl font-bold tracking-tight text-[#3b2b22] dark:text-[#f2e7db] sm:text-5xl">
          {t('welcome.title')}
        </h1>

        {/* Subtitle */}
        <p className="mb-12 text-lg text-[#7b6557] dark:text-[#c8b8aa] sm:text-xl">
          {t('welcome.subtitle')}
        </p>

        {/* Mode cards */}
        <div className="grid w-full max-w-2xl gap-4 sm:grid-cols-2">
          <motion.button
            type="button"
            onClick={() => onSelectMode('quick')}
            className={cn(
              modeCardBaseClass,
              'border-[#e7d8ca]/85 bg-[#fff9f3]/84 shadow-[0_24px_60px_-38px_rgba(170,107,66,0.36)]',
              'hover:border-[#d18b63] hover:bg-[#fffdf9] hover:shadow-[0_28px_64px_-36px_rgba(170,107,66,0.42)]',
              'focus-visible:ring-[#d18b63]/45',
              'dark:border-[#5b4437]/72 dark:bg-[#241c18]/88 dark:hover:border-[#c58a61] dark:hover:bg-[#2a201c]'
            )}
            whileHover={shouldReduceMotion ? undefined : { y: -4 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
          >
            <div className="absolute right-[-1.25rem] top-[-1.25rem] h-24 w-24 rounded-full bg-[#efc6a9]/36 blur-2xl dark:bg-[#7f573f]/22" />
            <div className="relative z-10 flex h-11 w-11 items-center justify-center rounded-xl bg-[#f6e1d0] text-[#b56d3c] transition group-hover:bg-[#f2d4be] dark:bg-[#3b2b23] dark:text-[#f0b489] dark:group-hover:bg-[#4a352b]">
              <Rocket className="h-5 w-5" />
            </div>
            <div className="relative z-10">
              <div className="text-lg font-semibold text-[#35261f] dark:text-[#f4eadf]">{t('welcome.quickMode')}</div>
              <p className="mt-1 text-sm leading-relaxed text-[#7d685a] dark:text-[#c8b7a7]">
                {t('welcome.quickModeDesc')}
              </p>
            </div>
          </motion.button>

          <motion.button
            type="button"
            onClick={() => onSelectMode('expert')}
            className={cn(
              modeCardBaseClass,
              'border-[#e7d8ca]/85 bg-[#fff9f3]/84 shadow-[0_24px_60px_-38px_rgba(170,107,66,0.36)]',
              'hover:border-[#d18b63] hover:bg-[#fffdf9] hover:shadow-[0_28px_64px_-36px_rgba(170,107,66,0.42)]',
              'focus-visible:ring-[#d18b63]/45',
              'dark:border-[#5b4437]/72 dark:bg-[#241c18]/88 dark:hover:border-[#c58a61] dark:hover:bg-[#2a201c]'
            )}
            whileHover={shouldReduceMotion ? undefined : { y: -4 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
          >
            <div className="absolute right-[-1.25rem] top-[-1.25rem] h-24 w-24 rounded-full bg-[#efc6a9]/36 blur-2xl dark:bg-[#7f573f]/22" />
            <div className="relative z-10 flex h-11 w-11 items-center justify-center rounded-xl bg-[#f6e1d0] text-[#b56d3c] transition group-hover:bg-[#f2d4be] dark:bg-[#3b2b23] dark:text-[#f0b489] dark:group-hover:bg-[#4a352b]">
              <Settings className="h-5 w-5" />
            </div>
            <div className="relative z-10">
              <div className="text-lg font-semibold text-[#35261f] dark:text-[#f4eadf]">{t('welcome.expertMode')}</div>
              <p className="mt-1 text-sm leading-relaxed text-[#7d685a] dark:text-[#c8b7a7]">
                {t('welcome.expertModeDesc')}
              </p>
            </div>
          </motion.button>
        </div>
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
