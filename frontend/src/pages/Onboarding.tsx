import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import OnboardingLoadError from '@/components/onboarding/OnboardingLoadError';
import { PluginInstallPanel } from '@/components/plugins/PluginInstallPanel';
import { STORAGE_KEYS } from '@/constants/app';
import { resolveInitialLanguage } from '@/utils/language';
import { configApi, SystemConfig } from '../api/modules/config';
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
  const [loadFailed, setLoadFailed] = useState(false);
  const requestIdRef = useRef(0);
  const navigate = useNavigate();
  const { t } = useTranslation('onboarding');

  const redirectIfCompleted = useCallback(async (): Promise<boolean> => {
    try {
      const response = await configApi.getOnboardingStatus();
      if (response.data?.completed === true) {
        localStorage.removeItem(STORAGE_KEY);
        navigate('/', { replace: true });
        return true;
      }
    } catch {
      // Keep the original template error visible when status cannot be confirmed.
    }
    return false;
  }, [navigate]);

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setConfig(null);
    setLoadFailed(false);
    try {
      const response = await configApi.getOnboardingTemplate();
      const template = response.data?.config;
      if (!template) {
        throw new Error('Onboarding template response is missing configuration');
      }

      const coreProviderId = template.llm?.selections?.core?.provider_id;
      const coreProvider = coreProviderId ? template.llm?.providers?.[coreProviderId] : undefined;

      // If onboarding is seeded from masked environment credentials, clear cached local edits.
      if (coreProvider?.services?.chat?.api_key?.endsWith('****')) {
        localStorage.removeItem(STORAGE_KEY);
      }

      if (requestId === requestIdRef.current) {
        setConfig(withInitialLanguage(template));
      }
    } catch {
      if (await redirectIfCompleted()) {
        return;
      }
      if (requestId === requestIdRef.current) {
        setLoadFailed(true);
      }
    }
  }, [redirectIfCompleted]);

  useEffect(() => {
    void load();
    return () => {
      requestIdRef.current += 1;
    };
  }, [load]);

  if (loadFailed) {
    return (
      <OnboardingLoadError
        title={t('page.loadConfigFailed')}
        description={t('page.loadConfigFailedDescription')}
        retryLabel={t('page.retryLoadConfig')}
        onRetry={() => void load()}
      />
    );
  }

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
