import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import enApp from './locales/en/app.json';
import enOnboarding from './locales/en/onboarding.json';
import enControl from './locales/en/control.json';
import zhApp from './locales/zh-CN/app.json';
import zhOnboarding from './locales/zh-CN/onboarding.json';
import zhControl from './locales/zh-CN/control.json';
import { resolveInitialLanguage, toI18nLanguage } from '@/utils/language';

const defaultLanguage = toI18nLanguage(resolveInitialLanguage());

void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': {
      app: zhApp,
      onboarding: zhOnboarding,
      control: zhControl,
    },
    en: {
      app: enApp,
      onboarding: enOnboarding,
      control: enControl,
    },
  },
  lng: defaultLanguage,
  fallbackLng: 'zh-CN',
  interpolation: {
    escapeValue: false,
  },
  defaultNS: 'app',
  ns: ['app', 'onboarding', 'control'],
});

document.documentElement.lang = defaultLanguage;

export default i18n;
