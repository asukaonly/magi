import type { LanguageCode } from '@/api/modules/config';
import { LANGUAGE_STORAGE_KEY } from '@/constants/settings';

type InitialLanguageOptions = {
  storedLanguage?: string | null;
  browserLanguage?: string | null;
};

type ConfigLanguageOptions = {
  storedLanguage?: string | null;
  onboardingCompleted?: boolean | null;
};

const normalizeStoredLanguage = (language?: string | null): LanguageCode | null => {
  if (language === 'en' || language === 'zh') {
    return language;
  }
  return null;
};

const readStoredLanguage = (): string | null => {
  if (typeof localStorage === 'undefined') {
    return null;
  }
  return localStorage.getItem(LANGUAGE_STORAGE_KEY);
};

const getBrowserLanguage = (language?: string | null): LanguageCode => {
  const rawLanguage = (language ?? (typeof navigator !== 'undefined' ? navigator.language : '')).toLowerCase();
  return rawLanguage.startsWith('zh') ? 'zh' : 'en';
};

export const getStoredLanguageSelection = (): LanguageCode | null =>
  normalizeStoredLanguage(readStoredLanguage());

export const resolveInitialLanguage = ({
  storedLanguage,
  browserLanguage,
}: InitialLanguageOptions = {}): LanguageCode => {
  const stored = storedLanguage === undefined ? readStoredLanguage() : storedLanguage;
  return normalizeStoredLanguage(stored) ?? getBrowserLanguage(browserLanguage);
};

export const toI18nLanguage = (language: LanguageCode): 'en' | 'zh-CN' =>
  language === 'zh' ? 'zh-CN' : 'en';

export const shouldApplyConfigLanguagePreference = ({
  storedLanguage,
  onboardingCompleted,
}: ConfigLanguageOptions = {}): boolean => {
  const stored = storedLanguage === undefined ? readStoredLanguage() : storedLanguage;
  return normalizeStoredLanguage(stored) !== null || onboardingCompleted === true;
};
