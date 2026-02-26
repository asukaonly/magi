import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { configApi, DEFAULT_SYSTEM_CONFIG, type LanguageCode, SystemConfig } from '../api/modules/config';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const STORAGE_KEY = 'magi_onboarding_state';
const LANGUAGE_KEY = 'magi_language';

// Detect browser language preference
const browserPreferredLanguage = (): 'en' | 'zh' => {
  const language = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : 'en';
  return language.startsWith('zh') ? 'zh' : 'en';
};

const OnboardingPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const { t } = useTranslation('onboarding');

  useEffect(() => {
    const load = async () => {
      try {
        const response = await configApi.getOnboardingTemplate();
        let template = response.data?.config || DEFAULT_SYSTEM_CONFIG;

        // If LLM config is from env, clear cache to ensure fresh state
        if (template.llm?.from_env) {
          localStorage.removeItem(STORAGE_KEY);
        }

        // Merge saved language preference
        const savedLanguage = localStorage.getItem(LANGUAGE_KEY);
        const language: LanguageCode = savedLanguage === 'en' || savedLanguage === 'zh'
          ? savedLanguage
          : browserPreferredLanguage();

        template = {
          ...template,
          preferences: {
            ...template.preferences,
            language,
          },
        };

        setConfig(template);
      } catch (error: any) {
        toast.error(error?.message || t('page.loadConfigFailed'));
        setConfig(DEFAULT_SYSTEM_CONFIG);
      }
    };
    void load();
  }, [t]);

  if (!config) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingSpinner className="h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30 p-6">
      <div className="mx-auto max-w-4xl">
        <OnboardingFlow initialConfig={config} />
      </div>
    </div>
  );
};

export default OnboardingPage;
