import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { PluginInstallPanel } from '@/components/plugins/PluginInstallPanel';
import { STORAGE_KEYS } from '@/constants/app';
import { resolveInitialLanguage } from '@/utils/language';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig } from '../api/modules/config';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const STORAGE_KEY = STORAGE_KEYS.ONBOARDING_STATE;

const withInitialLanguage = (config: SystemConfig): SystemConfig => {
  const language = resolveInitialLanguage();
  return {
    ...config,
    preferences: {
      ...config.preferences,
      language,
    },
  };
};

const OnboardingPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const { t } = useTranslation('onboarding');

  useEffect(() => {
    const load = async () => {
      try {
        const response = await configApi.getOnboardingTemplate();
        const template = response.data?.config || DEFAULT_SYSTEM_CONFIG;

        const coreProviderId = template.llm?.selections?.core?.provider_id;
        const coreProvider = coreProviderId ? template.llm?.providers?.[coreProviderId] : undefined;

        // If onboarding is seeded from masked environment credentials, clear cached local edits.
        if (coreProvider?.services?.chat?.api_key?.endsWith('****')) {
          localStorage.removeItem(STORAGE_KEY);
        }

        setConfig(withInitialLanguage(template));
      } catch (error: any) {
        toast.error(error?.message || t('page.loadConfigFailed'));
        setConfig(withInitialLanguage(DEFAULT_SYSTEM_CONFIG));
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
    <>
      <OnboardingFlow initialConfig={config} />
      <PluginInstallPanel />
    </>
  );
};

export default OnboardingPage;
