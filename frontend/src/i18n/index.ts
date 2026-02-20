import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import enApp from './locales/en/app.json';
import enOnboarding from './locales/en/onboarding.json';
import zhApp from './locales/zh-CN/app.json';
import zhOnboarding from './locales/zh-CN/onboarding.json';

const savedLanguage = localStorage.getItem('magi_language');
const defaultLanguage = savedLanguage === 'en' ? 'en' : 'zh-CN';

void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': {
      app: zhApp,
      onboarding: zhOnboarding,
    },
    en: {
      app: enApp,
      onboarding: enOnboarding,
    },
  },
  lng: defaultLanguage,
  fallbackLng: 'zh-CN',
  interpolation: {
    escapeValue: false,
  },
  defaultNS: 'app',
  ns: ['app', 'onboarding'],
});

document.documentElement.lang = defaultLanguage;

export default i18n;
