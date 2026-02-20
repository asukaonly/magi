import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig } from '../api/modules/config';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const OnboardingPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const response = await configApi.get();
        setConfig(response.data || DEFAULT_SYSTEM_CONFIG);
      } catch (error: any) {
        toast.error(error?.message || '加载配置失败');
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
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h2 className="mb-4 text-2xl font-semibold">首次使用引导</h2>
      <OnboardingFlow initialConfig={config} />
    </div>
  );
};

export default OnboardingPage;
