import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import OnboardingLoadError from '@/components/onboarding/OnboardingLoadError';
import { PluginInstallPanel } from '@/components/plugins/PluginInstallPanel';
import { DesktopTitleBar } from '@/components/layout/DesktopTitleBar';
import { STORAGE_KEYS } from '@/constants/app';
import { resolveInitialLanguage } from '@/utils/language';
import { configApi, SystemConfig } from '../api/modules/config';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';
import { sanitizeOnboardingProgressStorage } from '../components/onboarding/onboardingStorage';

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
    sanitizeOnboardingProgressStorage(STORAGE_KEY);

    const requestId = ++requestIdRef.current;
    setConfig(null);
    setLoadFailed(false);
    try {
      const response = await configApi.getOnboardingTemplate();
      const template = response.data?.config;
      if (!template) {
        throw new Error('Onboarding template response is missing configuration');
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

  let content: React.ReactNode;

  if (loadFailed) {
    content = (
      <OnboardingLoadError
        title={t('page.loadConfigFailed')}
        description={t('page.loadConfigFailedDescription')}
        retryLabel={t('page.retryLoadConfig')}
        onRetry={() => void load()}
      />
    );
  } else if (!config) {
    content = (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner className="h-8 w-8" />
      </div>
    );
  } else {
    content = (
      <>
        <OnboardingFlow initialConfig={config} />
        <PluginInstallPanel />
      </>
    );
  }

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background">
      <DesktopTitleBar />
      <div
        className="relative min-h-0 flex-1 overflow-hidden"
        data-testid="onboarding-window-content"
      >
        {content}
      </div>
    </div>
  );
};

export default OnboardingPage;
