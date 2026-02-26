import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig } from '../api/modules/config';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const OnboardingPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const { t } = useTranslation('onboarding');

  useEffect(() => {
    const load = async () => {
      try {
        const response = await configApi.getOnboardingTemplate();
        const template = response.data?.config || DEFAULT_SYSTEM_CONFIG;
        if (template.llm?.api_key === '***') {
          template.llm.api_key = '';
        }
        setConfig(template);
      } catch (error: any) {
        toast.error(error?.message || t('page.loadConfigFailed'));
        setConfig(DEFAULT_SYSTEM_CONFIG);
      }
    };
    void load();
  }, []);

  if (!config) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingSpinner className="h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="relative mx-auto max-w-4xl px-4 py-8">
      <div className="pointer-events-none absolute top-0 right-4 h-28 w-28 rounded-full bg-teal-500/10 blur-3xl" />
      <div className="pointer-events-none absolute top-24 left-0 h-24 w-24 rounded-full bg-cyan-500/10 blur-3xl" />
      <div className="relative mb-4 flex items-end justify-between gap-3">
        <h2 className="text-2xl font-semibold">{t('page.title')}</h2>
        <span className="rounded-full border border-border bg-background/80 px-3 py-1 text-xs text-muted-foreground">
          {t('page.badge')}
        </span>
      </div>
      <OnboardingFlow initialConfig={config} />
    </div>
  );
};

export default OnboardingPage;
