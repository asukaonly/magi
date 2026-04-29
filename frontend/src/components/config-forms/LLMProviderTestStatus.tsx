import { CheckCircle2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TestLLMProviderConnectionResponse } from '@/api/modules/config';

interface LLMProviderTestStatusProps {
  error: string | null;
  result: TestLLMProviderConnectionResponse | null;
}

export function LLMProviderTestStatus({ error, result }: LLMProviderTestStatusProps) {
  const { t } = useTranslation('onboarding');

  return (
    <>
      {error ? (
        <div className="flex items-start gap-2 rounded-xl bg-destructive/8 px-3 py-2.5 text-sm text-destructive">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="space-y-0.5">
            <div className="font-medium">{t('llm.providerConfiguration.testFailed')}</div>
            <p>{error}</p>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-emerald-500/10 px-3 py-2.5 text-sm text-emerald-900 dark:text-emerald-200">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span className="font-medium">{t('llm.providerConfiguration.testSuccess')}</span>
          <span>
            {t('llm.providerConfiguration.testSuccessMeta', {
              model: result.model,
              latency: result.latency_ms,
            })}
          </span>
          {result.preview ? (
            <span className="text-emerald-900/80 dark:text-emerald-100/80">
              {t('llm.providerConfiguration.testPreview', { preview: result.preview })}
            </span>
          ) : null}
        </div>
      ) : null}
    </>
  );
}